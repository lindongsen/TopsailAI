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
func (s *Store) ListRecordedReceipts(ctx context.Context) ([]protocol.ExecutionReceipt, error) {
	rows, err := s.db.QueryContext(ctx, `SELECT receipt_json FROM command_journal WHERE phase = ? AND receipt_json IS NOT NULL ORDER BY updated_at_ms ASC, command_id ASC`, protocol.PhaseReceiptRecorded)
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
