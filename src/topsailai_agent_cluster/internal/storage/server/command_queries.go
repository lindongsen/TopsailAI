package serverstorage

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"

	"topsailai_agent_cluster/internal/protocol"
)

// ListCommands returns recent commands for one endpoint or resource.
func (s *Store) ListCommands(ctx context.Context, endpointID, resourceID string, limit int) ([]CommandRecord, error) {
	if limit <= 0 || limit > 100 {
		limit = 20
	}
	query := `SELECT command_id, request_hash, endpoint_id, operation, intent_json, status, phase, delivery_boundary, effect_certainty, deadline_at_ms, create_at_ms, receipt_json FROM commands WHERE (? = '' OR endpoint_id = ?) AND (? = '' OR json_extract(target_json, '$.resource_id') = ?) ORDER BY create_at_ms DESC, command_id DESC LIMIT ?`
	rows, err := s.db.QueryContext(ctx, query, endpointID, endpointID, resourceID, resourceID, limit)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	var records []CommandRecord
	for rows.Next() {
		var record CommandRecord
		var status, phase, boundary, certainty string
		var receiptJSON []byte
		if err := rows.Scan(&record.CommandID, &record.RequestHash, &record.EndpointID, &record.Operation, &record.IntentJSON, &status, &phase, &boundary, &certainty, &record.DeadlineAtMS, &record.CreateAtMS, &receiptJSON); err != nil {
			return nil, err
		}
		record.Status = protocol.CommandStatus(status)
		record.Phase = protocol.CommandPhase(phase)
		record.DeliveryBoundary = protocol.DeliveryBoundary(boundary)
		record.EffectCertainty = protocol.EffectCertainty(certainty)
		if len(receiptJSON) > 0 {
			var receipt protocol.ExecutionReceipt
			if json.Unmarshal(receiptJSON, &receipt) == nil {
				record.ErrorCode, record.ExitConfirmed = receipt.ErrorCode, receipt.ExitConfirmed
			}
		}
		record.IntentJSON = nil
		record.RequestHash = ""
		records = append(records, record)
	}
	return records, rows.Err()
}

// GetCommand returns the durable command projection.
func (s *Store) GetCommand(ctx context.Context, commandID string) (CommandRecord, error) {
	var record CommandRecord
	var status, phase, boundary, certainty string
	var intent []byte
	err := s.db.QueryRowContext(ctx, `SELECT command_id, request_hash, endpoint_id, operation, intent_json, status, phase, delivery_boundary, effect_certainty, deadline_at_ms, create_at_ms FROM commands WHERE command_id = ?`, commandID).Scan(&record.CommandID, &record.RequestHash, &record.EndpointID, &record.Operation, &intent, &status, &phase, &boundary, &certainty, &record.DeadlineAtMS, &record.CreateAtMS)
	if err == sql.ErrNoRows {
		return record, fmt.Errorf("command %q not found", commandID)
	}
	if err != nil {
		return record, err
	}
	record.IntentJSON = intent
	record.Status = protocol.CommandStatus(status)
	record.Phase = protocol.CommandPhase(phase)
	record.DeliveryBoundary = protocol.DeliveryBoundary(boundary)
	record.EffectCertainty = protocol.EffectCertainty(certainty)
	var receipt protocol.ExecutionReceipt
	var receiptJSON []byte
	if err := s.db.QueryRowContext(ctx, `SELECT receipt_json FROM commands WHERE command_id = ?`, commandID).Scan(&receiptJSON); err == nil && len(receiptJSON) > 0 {
		if err := json.Unmarshal(receiptJSON, &receipt); err == nil {
			record.ErrorCode = receipt.ErrorCode
			record.ExitConfirmed = receipt.ExitConfirmed
		}
	}
	return record, nil
}

// DispatchCommand atomically claims an admitted command before transport handoff.
func (s *Store) DispatchCommand(ctx context.Context, commandID string, nowMS int64) (bool, error) {
	result, err := s.db.ExecContext(ctx, `UPDATE commands SET status = ?, update_at_ms = ? WHERE command_id = ? AND status = ?`, protocol.StatusDispatched, nowMS, commandID, protocol.StatusAdmitted)
	if err != nil {
		return false, err
	}
	n, err := result.RowsAffected()
	return n == 1, err
}

// ApplyReceipt persists a receipt and rejects stale revisions while accepting exact retries.
func (s *Store) ApplyReceipt(ctx context.Context, receipt protocol.ExecutionReceipt, nowMS int64) error {
	if receipt.EffectCertainty == protocol.EffectNotApplied && receipt.ErrorCode == "" {
		receipt.ErrorCode = "not_applied"
	}
	data, err := json.Marshal(receipt)
	if err != nil {
		return err
	}
	var existing []byte
	err = s.db.QueryRowContext(ctx, `SELECT receipt_json FROM commands WHERE command_id=? AND request_hash=?`, receipt.CommandID, receipt.RequestHash).Scan(&existing)
	if err == sql.ErrNoRows {
		return fmt.Errorf("command %q does not match a stored intent", receipt.CommandID)
	}
	if err != nil {
		return err
	}
	if len(existing) > 0 {
		var prior protocol.ExecutionReceipt
		if err := json.Unmarshal(existing, &prior); err != nil {
			return fmt.Errorf("decode stored receipt: %w", err)
		}
		if receipt.CommandRevision < prior.CommandRevision {
			return fmt.Errorf("receipt revision %d is older than stored revision %d", receipt.CommandRevision, prior.CommandRevision)
		}
		if receipt.CommandRevision == prior.CommandRevision {
			if string(existing) == string(data) {
				return nil
			}
			return fmt.Errorf("receipt revision %d conflicts with stored receipt", receipt.CommandRevision)
		}
	}
	status := protocol.StatusFinished
	if receipt.EffectCertainty == protocol.EffectUnknown {
		status = protocol.StatusExecuting
	}
	if receipt.Outcome == "endpoint_admitted" {
		status = protocol.StatusEndpointAdmitted
	}
	if receipt.EffectCertainty == protocol.EffectNotApplied {
		status = protocol.StatusRejected
	}
	if receipt.DeliveryBoundary == protocol.DeliverySignalSent && !receipt.ExitConfirmed {
		status = protocol.StatusExecuting
	}
	_, err = s.db.ExecContext(ctx, `UPDATE commands SET status=?, phase=?, delivery_boundary=?, effect_certainty=?, receipt_json=?, update_at_ms=? WHERE command_id=? AND request_hash=?`, status, receipt.Phase, receipt.DeliveryBoundary, receipt.EffectCertainty, data, nowMS, receipt.CommandID, receipt.RequestHash)
	return err
}
