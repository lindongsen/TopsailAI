package serverstorage

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"strings"
	"time"

	"topsailai_agent_cluster/internal/protocol"
)

// CommandRecord is the durable command projection used for deduplication.
// ProviderResponse is the provider's own return document, stored and returned
// verbatim. Server never parses it, so it stays opaque descriptive evidence.
type CommandRecord struct {
	CommandID                 string                    `json:"command_id"`
	RequestHash               string                    `json:"request_hash"`
	EndpointID                string                    `json:"endpoint_id"`
	Operation                 string                    `json:"operation"`
	IntentJSON                []byte                    `json:"intent_json"`
	Status                    protocol.CommandStatus    `json:"status"`
	Phase                     protocol.CommandPhase     `json:"phase"`
	DeliveryBoundary          protocol.DeliveryBoundary `json:"delivery_boundary"`
	EffectCertainty           protocol.EffectCertainty  `json:"effect_certainty"`
	ExitConfirmed             bool                      `json:"exit_confirmed"`
	ErrorCode                 string                    `json:"error_code,omitempty"`
	ProviderResponse          string                    `json:"provider_response,omitempty"`
	ProviderResponseTruncated bool                      `json:"provider_response_truncated,omitempty"`
	DeadlineAtMS              int64                     `json:"deadline_at_ms"`
	CreateAtMS                int64                     `json:"create_at_ms"`
}

// MarshalJSON preserves the legacy exported field names while exposing stable snake-case fields.
func (r CommandRecord) MarshalJSON() ([]byte, error) {
	type recordAlias CommandRecord
	data, err := json.Marshal(recordAlias(r))
	if err != nil {
		return nil, err
	}
	var fields map[string]any
	if err := json.Unmarshal(data, &fields); err != nil {
		return nil, err
	}
	fields["CommandID"] = r.CommandID
	fields["RequestHash"] = r.RequestHash
	fields["EndpointID"] = r.EndpointID
	fields["Operation"] = r.Operation
	fields["Status"] = r.Status
	fields["Phase"] = r.Phase
	fields["DeliveryBoundary"] = r.DeliveryBoundary
	fields["EffectCertainty"] = r.EffectCertainty
	fields["ExitConfirmed"] = r.ExitConfirmed
	fields["ErrorCode"] = r.ErrorCode
	fields["ProviderResponse"] = r.ProviderResponse
	fields["ProviderResponseTruncated"] = r.ProviderResponseTruncated
	fields["DeadlineAtMS"] = r.DeadlineAtMS
	fields["CreateAtMS"] = r.CreateAtMS
	return json.Marshal(fields)
}

// AdmitCommand inserts a command or returns a conflict for a changed intent.
func (s *Store) AdmitCommand(ctx context.Context, intent protocol.ImmutableIntent, requestHash string, nowMS int64) error {
	if intent.CommandID == "" || intent.EndpointID == "" || requestHash == "" {
		return fmt.Errorf("command identity is required")
	}
	payload, err := json.Marshal(intent)
	if err != nil {
		return err
	}
	_, err = s.db.ExecContext(ctx, `INSERT INTO commands(command_id, request_hash, endpoint_id, operation, target_json, intent_json, status, phase, delivery_boundary, effect_certainty, deadline_at_ms, create_at_ms, update_at_ms) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`, intent.CommandID, requestHash, intent.EndpointID, intent.Operation, nullableTarget(intent.Target), payload, protocol.StatusAdmitted, protocol.PhaseAccepted, protocol.DeliveryNotStarted, protocol.EffectNotApplied, intent.ExecuteBeforeAtMS, nowMS, nowMS)
	if err != nil {
		if isConstraint(err) {
			var existing string
			queryErr := s.db.QueryRowContext(ctx, `SELECT request_hash FROM commands WHERE command_id = ?`, intent.CommandID).Scan(&existing)
			if queryErr == nil {
				if existing != requestHash {
					return fmt.Errorf("command ID conflicts with a different intent")
				}
				return nil
			}
			return err
		}
		return err
	}
	return nil
}

// ExpireCommand marks an admitted command as not applied when its deadline has passed.
func (s *Store) ExpireCommand(ctx context.Context, commandID string, nowMS int64) (bool, error) {
	result, err := s.db.ExecContext(ctx, `UPDATE commands SET status = ?, effect_certainty = ?, update_at_ms = ? WHERE command_id = ? AND status = ?`, protocol.StatusExpired, protocol.EffectNotApplied, nowMS, commandID, protocol.StatusAdmitted)
	if err != nil {
		return false, err
	}
	affected, err := result.RowsAffected()
	return affected == 1, err
}

// ReconcileExpiredCommands converges commands that are still executing past their
// immutable deadline into the terminal unconfirmed state. Delivery already happened
// for these rows, so the effect certainty becomes unknown instead of not_applied: the
// operator must not be told that a signal which was sent had no effect. The update is
// conditional and idempotent, so repeated reconciliation cannot overwrite a later
// authoritative receipt that already reached finished, rejected or failed.
func (s *Store) ReconcileExpiredCommands(ctx context.Context, nowMS int64) (int64, error) {
	result, err := s.db.ExecContext(ctx, `UPDATE commands SET status = ?, effect_certainty = ?, update_at_ms = ? WHERE status = ? AND deadline_at_ms > 0 AND deadline_at_ms <= ?`, protocol.StatusUnconfirmed, protocol.EffectUnknown, nowMS, protocol.StatusExecuting, nowMS)
	if err != nil {
		return 0, err
	}
	return result.RowsAffected()
}

// CancelCommand atomically cancels a command only before dispatch.
func (s *Store) CancelCommand(ctx context.Context, commandID string, nowMS int64) (bool, error) {
	for attempt := 0; attempt < 20; attempt++ {
		result, err := s.db.ExecContext(ctx, `UPDATE commands SET status = ?, update_at_ms = ? WHERE command_id = ? AND status = ?`, protocol.StatusCancelled, nowMS, commandID, protocol.StatusAdmitted)
		if err == nil {
			affected, rowsErr := result.RowsAffected()
			return affected == 1, rowsErr
		}
		if !strings.Contains(err.Error(), "locked") {
			return false, err
		}
		select {
		case <-ctx.Done():
			return false, ctx.Err()
		case <-time.After(5 * time.Millisecond):
		}
	}
	return false, fmt.Errorf("cancel command: database remained locked")
}

// PurgeExpiredCommands deletes terminal command records older than the cutoff.
//
// The status list is an allowlist rather than a denylist, so a status added
// later is retained until someone decides it is safe to delete. A denylist
// would silently start deleting the new status the moment it was introduced.
//
// unconfirmed is deliberately excluded even though it is terminal for polling.
// Its effect is unknown: delivery happened and the exit was never confirmed, so
// an operator investigating an unknown effect still needs the row. It is
// retained until an explicit reconciliation resolves it.
//
// Deleting a row removes the duplicate-detection evidence for that command ID,
// and that is safe because the immutable deadline, not the stored row, is what
// prevents a replayed expired command from executing: admission re-inserts the
// row and immediately expires it when ExecuteBeforeAtMS has passed.
func (s *Store) PurgeExpiredCommands(ctx context.Context, cutoffMS int64) (int64, error) {
	if cutoffMS <= 0 {
		return 0, fmt.Errorf("command purge cutoff must be positive")
	}
	result, err := s.db.ExecContext(ctx, `DELETE FROM commands WHERE update_at_ms <= ? AND status IN (?, ?, ?, ?, ?)`, cutoffMS, protocol.StatusFinished, protocol.StatusRejected, protocol.StatusFailed, protocol.StatusExpired, protocol.StatusCancelled)
	if err != nil {
		return 0, fmt.Errorf("purge expired commands: %w", err)
	}
	purged, err := result.RowsAffected()
	if err != nil {
		return 0, fmt.Errorf("count purged commands: %w", err)
	}
	return purged, nil
}

func nullableTarget(target *protocol.CommandTarget) any {
	if target == nil {
		return nil
	}
	data, _ := json.Marshal(target)
	return string(data)
}

func isConstraint(err error) bool {
	return err != nil && (err == sql.ErrNoRows || contains(err.Error(), "constraint") || contains(err.Error(), "UNIQUE"))
}

func contains(value, fragment string) bool {
	for i := 0; i+len(fragment) <= len(value); i++ {
		if value[i:i+len(fragment)] == fragment {
			return true
		}
	}
	return false
}
