package endpointstorage

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"

	"topsailai_agent_cluster/internal/protocol"
)

// JournalEntry is the durable record used to prevent repeated command effects.
type JournalEntry struct {
	CommandID   string
	RequestHash string
	IntentJSON  string
	Phase       protocol.CommandPhase
	ReceiptJSON string
}

// AdmitJournal inserts a command or returns its existing record. A hash mismatch is a conflict.
func (s *Store) AdmitJournal(ctx context.Context, intent protocol.ImmutableIntent, requestHash string, nowMS int64) (JournalEntry, bool, error) {
	if intent.CommandID == "" || requestHash == "" || nowMS < 1 {
		return JournalEntry{}, false, errors.New("command ID, request hash and timestamp are required")
	}
	intentJSON, err := json.Marshal(intent)
	if err != nil {
		return JournalEntry{}, false, fmt.Errorf("marshal intent: %w", err)
	}
	result, err := s.db.ExecContext(ctx, `INSERT INTO command_journal(command_id, request_hash, intent_json, phase, created_at_ms, updated_at_ms) VALUES(?, ?, ?, ?, ?, ?) ON CONFLICT(command_id) DO NOTHING`, intent.CommandID, requestHash, intentJSON, protocol.PhaseAccepted, nowMS, nowMS)
	if err != nil {
		return JournalEntry{}, false, fmt.Errorf("admit command: %w", err)
	}
	inserted, err := result.RowsAffected()
	if err != nil {
		return JournalEntry{}, false, err
	}
	entry, err := s.journalEntry(ctx, intent.CommandID)
	if err != nil {
		return JournalEntry{}, false, err
	}
	if entry.RequestHash != requestHash {
		return JournalEntry{}, false, fmt.Errorf("command %q conflicts with existing request", intent.CommandID)
	}
	return entry, inserted == 1, nil
}

// MarkInvocationStarted atomically records the boundary before an external call.
func (s *Store) MarkInvocationStarted(ctx context.Context, commandID string, nowMS int64) error {
	result, err := s.db.ExecContext(ctx, `UPDATE command_journal SET phase=?, updated_at_ms=? WHERE command_id=? AND phase=?`, protocol.PhaseInvocationStarted, nowMS, commandID, protocol.PhaseAccepted)
	if err != nil {
		return fmt.Errorf("mark invocation started: %w", err)
	}
	if affected, _ := result.RowsAffected(); affected != 1 {
		return fmt.Errorf("command %q is not accepted", commandID)
	}
	return nil
}

// MarkEndpointAdmitted atomically records durable Endpoint admission before provider invocation.
func (s *Store) MarkEndpointAdmitted(ctx context.Context, commandID string, nowMS int64) error {
	result, err := s.db.ExecContext(ctx, `UPDATE command_journal SET phase=?, updated_at_ms=? WHERE command_id=? AND phase=?`, protocol.PhaseEndpointAdmitted, nowMS, commandID, protocol.PhaseInvocationStarted)
	if err != nil {
		return fmt.Errorf("mark endpoint admitted: %w", err)
	}
	if affected, _ := result.RowsAffected(); affected != 1 {
		return fmt.Errorf("command %q is not invocation-started", commandID)
	}
	return nil
}

// RecordReceipt atomically stores a provider receipt after invocation.
func (s *Store) RecordReceipt(ctx context.Context, commandID string, receipt protocol.ExecutionReceipt, nowMS int64) error {
	if receipt.CommandID != commandID {
		return errors.New("receipt command ID does not match journal command")
	}
	data, err := json.Marshal(receipt)
	if err != nil {
		return fmt.Errorf("marshal receipt: %w", err)
	}
	result, err := s.db.ExecContext(ctx, `UPDATE command_journal SET phase=?, receipt_json=?, updated_at_ms=? WHERE command_id=? AND phase IN (?, ?, ?)`, protocol.PhaseReceiptRecorded, data, nowMS, commandID, protocol.PhaseAccepted, protocol.PhaseInvocationStarted, protocol.PhaseEndpointAdmitted)
	if err != nil {
		return fmt.Errorf("record receipt: %w", err)
	}
	if affected, _ := result.RowsAffected(); affected != 1 {
		return fmt.Errorf("command %q is not invocation-started", commandID)
	}
	return nil
}

// GetJournal returns a command journal entry, including an unknown-effect phase when no receipt exists.
func (s *Store) GetJournal(ctx context.Context, commandID string) (JournalEntry, error) {
	return s.journalEntry(ctx, commandID)
}

func (s *Store) journalEntry(ctx context.Context, commandID string) (JournalEntry, error) {
	var entry JournalEntry
	var phase string
	err := s.db.QueryRowContext(ctx, `SELECT command_id, request_hash, intent_json, phase, COALESCE(receipt_json, '') FROM command_journal WHERE command_id=?`, commandID).Scan(&entry.CommandID, &entry.RequestHash, &entry.IntentJSON, &phase, &entry.ReceiptJSON)
	if errors.Is(err, sql.ErrNoRows) {
		return JournalEntry{}, fmt.Errorf("command %q not found", commandID)
	}
	if err != nil {
		return JournalEntry{}, err
	}
	entry.Phase = protocol.CommandPhase(phase)
	return entry, nil
}

// ListAcceptedCommands returns commands admitted before invocation began.
func (s *Store) ListAcceptedCommands(ctx context.Context) ([]JournalEntry, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT command_id, request_hash, intent_json, phase, COALESCE(receipt_json, '') FROM command_journal WHERE phase = ? ORDER BY updated_at_ms ASC, command_id ASC`, protocol.PhaseAccepted)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	entries := make([]JournalEntry, 0)
	for rows.Next() {
		var entry JournalEntry
		var phase string
		if err := rows.Scan(&entry.CommandID, &entry.RequestHash, &entry.IntentJSON, &phase, &entry.ReceiptJSON); err != nil {
			return nil, err
		}
		entry.Phase = protocol.CommandPhase(phase)
		entries = append(entries, entry)
	}
	return entries, rows.Err()
}

// ListRecordedReceipts returns durable receipts that still need transport acknowledgement.
//
// A receipt the current Server proved it can never apply is excluded, because
// re-sending it on every reconnect is the loop this settlement exists to stop.
// The journal row itself is untouched, so the evidence that the receipt existed
// remains readable.
func (s *Store) ListRecordedReceipts(ctx context.Context) ([]protocol.ExecutionReceipt, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT receipt_json FROM command_journal WHERE phase = ? AND receipt_json IS NOT NULL AND NOT EXISTS (SELECT 1 FROM receipt_settlement WHERE receipt_settlement.command_id = command_journal.command_id) ORDER BY updated_at_ms ASC, command_id ASC`, protocol.PhaseReceiptRecorded)
	if err != nil {
		return nil, err
	}
	defer rows.Close()
	result := make([]protocol.ExecutionReceipt, 0)
	for rows.Next() {
		var raw string
		if err := rows.Scan(&raw); err != nil {
			return nil, err
		}
		var receipt protocol.ExecutionReceipt
		if err := json.Unmarshal([]byte(raw), &receipt); err != nil {
			return nil, fmt.Errorf("decode recorded receipt: %w", err)
		}
		result = append(result, receipt)
	}
	return result, rows.Err()
}

// SettleReceipt records that a receipt must never be re-sent, because the
// current Server either proved it can never apply it or already stored it.
//
// Settlement is durable rather than in-memory because the pending set is
// reloaded from the journal on every reconnect. Clearing only the in-memory map
// would let the next reconnect re-send exactly the receipts that were just
// settled, which is the loop this method exists to end.
//
// The origin is stored so an operator can tell a delivery confirmation from a
// refusal without reading logs, and the rejection reason is stored alongside it
// so a re-homing artefact can be told from an integrity disagreement. An
// acknowledgement carries no rejection reason, so reason is NULL for it rather
// than an empty string: an empty value that means something is the implicit
// contract this schema avoids.
func (s *Store) SettleReceipt(ctx context.Context, commandID string, origin protocol.SettlementOrigin, reason protocol.ReceiptRejection, nowMS int64) error {
	if commandID == "" {
		return errors.New("command id is required to settle a receipt")
	}
	if origin == "" {
		return errors.New("settlement origin is required to settle a receipt")
	}
	if origin == protocol.SettlementOriginRejection && reason == "" {
		return errors.New("a rejection settlement requires a rejection reason")
	}
	if origin == protocol.SettlementOriginAcknowledgement && reason != "" {
		return fmt.Errorf("an acknowledgement settlement carries no rejection reason, got %q", reason)
	}
	_, err := s.db.ExecContext(ctx, `INSERT INTO receipt_settlement(command_id, reason, settled_by, settled_at_ms) VALUES(?,?,?,?) ON CONFLICT(command_id) DO UPDATE SET reason=excluded.reason, settled_by=excluded.settled_by, settled_at_ms=excluded.settled_at_ms`, commandID, nullableReason(origin, reason), string(origin), nowMS)
	return err
}

// nullableReason returns the rejection reason to store, or nil when the
// settlement is an acknowledgement.
//
// The conversion lives here rather than at each call site so no caller can
// accidentally store an empty string where NULL is the contract.
func nullableReason(origin protocol.SettlementOrigin, reason protocol.ReceiptRejection) any {
	if origin != protocol.SettlementOriginRejection {
		return nil
	}
	return string(reason)
}

// SettleAllRecordedReceipts settles every receipt still awaiting acknowledgement
// and returns how many rows were settled.
//
// It exists for the re-home case, where the Endpoint learns in one step that the
// Server it now talks to is not the one that admitted those commands. Settling
// them individually would require one round trip per receipt, and the outcome is
// already known: a Server that never admitted a command can never apply its
// receipt.
//
// Every row this method writes is a rejection, because the caller supplies the
// reason that proves the receipt can never be applied. The origin column is
// therefore a literal rather than a parameter: a bulk settlement has no
// acknowledgement case, and accepting an origin here would let a caller write an
// acknowledgement with no evidence that the Server stored anything.
func (s *Store) SettleAllRecordedReceipts(ctx context.Context, reason protocol.ReceiptRejection, nowMS int64) (int64, error) {
	if reason == "" {
		return 0, errors.New("a bulk settlement requires a rejection reason")
	}
	result, err := s.db.ExecContext(ctx, `INSERT INTO receipt_settlement(command_id, reason, settled_by, settled_at_ms) SELECT command_id, ?, ?, ? FROM command_journal WHERE phase = ? AND receipt_json IS NOT NULL AND NOT EXISTS (SELECT 1 FROM receipt_settlement WHERE receipt_settlement.command_id = command_journal.command_id)`, string(reason), string(protocol.SettlementOriginRejection), nowMS, protocol.PhaseReceiptRecorded)
	if err != nil {
		return 0, err
	}
	return result.RowsAffected()
}

// ObserveServerIdentity records the Server database identity this Endpoint is
// now talking to and reports whether it differs from the last one observed.
//
// The comparison is what makes a re-home detectable. A restarted Server keeps
// its identity because the value lives in the Server database, so a restart
// reports no change and its receipts are re-sent as usual. A different Server
// reports a change, which is the only case where recorded receipts can never be
// applied.
//
// An empty identity is never recorded and never reports a change. An older
// Server that does not send the field must not be mistaken for a new Server,
// because that would discard receipts the same Server still holds.
func (s *Store) ObserveServerIdentity(ctx context.Context, identity string, nowMS int64) (bool, error) {
	if identity == "" {
		return false, nil
	}
	var previous string
	err := s.db.QueryRowContext(ctx, `SELECT identity FROM server_identity_seen WHERE id = 1`).Scan(&previous)
	switch {
	case errors.Is(err, sql.ErrNoRows):
		// The first observation is not a change: there is no previous Server to
		// differ from, so nothing may be discarded on the strength of it.
		_, insertErr := s.db.ExecContext(ctx, `INSERT INTO server_identity_seen(id, identity, observed_at_ms) VALUES(1, ?, ?) ON CONFLICT(id) DO UPDATE SET identity=excluded.identity, observed_at_ms=excluded.observed_at_ms`, identity, nowMS)
		return false, insertErr
	case err != nil:
		return false, err
	}
	if previous == identity {
		return false, nil
	}
	if _, err := s.db.ExecContext(ctx, `UPDATE server_identity_seen SET identity = ?, observed_at_ms = ? WHERE id = 1`, identity, nowMS); err != nil {
		return false, err
	}
	return true, nil
}
