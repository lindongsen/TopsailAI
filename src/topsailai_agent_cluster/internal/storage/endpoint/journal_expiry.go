package endpointstorage

import (
	"context"
	"encoding/json"
	"fmt"

	"topsailai_agent_cluster/internal/protocol"
)

// ExpiredJournalEntry describes one command journal row removed by retention, so
// the caller can log the deletion with enough detail to audit it later.
type ExpiredJournalEntry struct {
	CommandID       string
	Phase           protocol.CommandPhase
	EffectCertainty string
	CreatedAtMS     int64
}

// ExpireCommandJournal deletes settled receipts older than cutoffMS and returns
// what it removed.
//
// Only a settled receipt_recorded row is eligible. Such a row is a receipt the
// current Server already proved it can never apply, so the Endpoint has stopped
// re-sending it and the row is pure history. Deleting it removes no capability:
// the command itself is gone from the Server that admitted it, which is exactly
// why the receipt was settled.
//
// Four kinds of row are deliberately kept, because each one is the only evidence
// of something an operator may still need:
//
//   - accepted: the command was admitted but never executed. This is the record
//     an operator reconciles after an interrupted command, and it is the only
//     proof that the Endpoint received an intent it never acted on.
//   - invocation_started and endpoint_admitted: the provider may have acted. The
//     effect is unknown, so the row is the only evidence that an uncertain
//     operation exists.
//   - receipt_recorded without a settlement row: the receipt is still pending
//     acknowledgement, so deleting it would silently drop evidence the Server has
//     not yet answered.
//
// The settlement row is deleted in the same transaction as the journal row, so a
// crash cannot leave a settlement pointing at a command that no longer exists.
func (s *Store) ExpireCommandJournal(ctx context.Context, cutoffMS int64) ([]ExpiredJournalEntry, error) {
	if cutoffMS < 1 {
		return nil, fmt.Errorf("command journal expiry cutoff must be positive")
	}
	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return nil, fmt.Errorf("begin command journal expiry: %w", err)
	}
	defer tx.Rollback()
	rows, err := tx.QueryContext(ctx, `SELECT command_id, phase, COALESCE(receipt_json, ''), created_at_ms FROM command_journal WHERE phase = ? AND created_at_ms < ? AND EXISTS (SELECT 1 FROM receipt_settlement WHERE receipt_settlement.command_id = command_journal.command_id) ORDER BY created_at_ms ASC, command_id ASC`, protocol.PhaseReceiptRecorded, cutoffMS)
	if err != nil {
		return nil, fmt.Errorf("select expired command journal: %w", err)
	}
	var expired []ExpiredJournalEntry
	for rows.Next() {
		var entry ExpiredJournalEntry
		var phase string
		var receiptJSON string
		if err := rows.Scan(&entry.CommandID, &phase, &receiptJSON, &entry.CreatedAtMS); err != nil {
			rows.Close()
			return nil, fmt.Errorf("scan expired command journal: %w", err)
		}
		entry.Phase = protocol.CommandPhase(phase)
		entry.EffectCertainty = receiptEffectCertainty(receiptJSON)
		expired = append(expired, entry)
	}
	if err := rows.Close(); err != nil {
		return nil, fmt.Errorf("close expired command journal rows: %w", err)
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("iterate expired command journal: %w", err)
	}
	if len(expired) == 0 {
		if err := tx.Commit(); err != nil {
			return nil, fmt.Errorf("commit command journal expiry: %w", err)
		}
		return nil, nil
	}
	for _, entry := range expired {
		if _, err := tx.ExecContext(ctx, `DELETE FROM receipt_settlement WHERE command_id = ?`, entry.CommandID); err != nil {
			return nil, fmt.Errorf("delete expired receipt settlement: %w", err)
		}
		if _, err := tx.ExecContext(ctx, `DELETE FROM command_journal WHERE command_id = ? AND phase = ?`, entry.CommandID, string(protocol.PhaseReceiptRecorded)); err != nil {
			return nil, fmt.Errorf("delete expired command journal: %w", err)
		}
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("commit command journal expiry: %w", err)
	}
	return expired, nil
}

// receiptEffectCertainty extracts the effect certainty from a stored receipt so a
// deletion log can state whether the removed command was known to have applied.
// An unreadable receipt yields an empty value rather than an error: retention must
// not be blocked by one malformed row, and the log then shows that the certainty
// was unknown.
func receiptEffectCertainty(receiptJSON string) string {
	if receiptJSON == "" {
		return ""
	}
	var receipt protocol.ExecutionReceipt
	if err := json.Unmarshal([]byte(receiptJSON), &receipt); err != nil {
		return ""
	}
	return string(receipt.EffectCertainty)
}
