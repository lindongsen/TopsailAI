package serverstorage

import (
	"context"
	"crypto/rand"
	"database/sql"
	"encoding/hex"
	"errors"
	"fmt"
)

// ServerIdentity returns this Server database's durable identity, creating it on
// first use.
//
// The identity answers one question for an Endpoint: is the Server I am talking
// to now the same Server that admitted my recorded commands? That question
// decides whether those receipts may be discarded, because a Server that never
// admitted a command can never apply its receipt.
//
// It is durable rather than per-process on purpose. A per-process value would
// change on every restart, so an Endpoint would abandon receipts that the
// restarted Server still holds and could still apply. Storing it in the database
// makes "same database" and "same identity" the same fact, which is exactly the
// condition that makes a receipt applicable.
func (s *Store) ServerIdentity(ctx context.Context) (string, error) {
	var identity string
	err := s.db.QueryRowContext(ctx, `SELECT identity FROM server_identity WHERE id = 1`).Scan(&identity)
	if err == nil {
		return identity, nil
	}
	if !errors.Is(err, sql.ErrNoRows) {
		return "", fmt.Errorf("read server identity: %w", err)
	}
	generated, err := newServerIdentity()
	if err != nil {
		return "", err
	}
	// The insert is conditional so two concurrent callers cannot disagree about
	// the identity: the first writer wins and the second reads what it wrote.
	if _, err := s.db.ExecContext(ctx, `INSERT INTO server_identity(id, identity) VALUES(1, ?) ON CONFLICT(id) DO NOTHING`, generated); err != nil {
		return "", fmt.Errorf("create server identity: %w", err)
	}
	if err := s.db.QueryRowContext(ctx, `SELECT identity FROM server_identity WHERE id = 1`).Scan(&identity); err != nil {
		return "", fmt.Errorf("read created server identity: %w", err)
	}
	return identity, nil
}

// newServerIdentity mints one opaque identity value.
//
// It is random rather than derived from the database path or hostname, because
// two Servers can legitimately share a path on different machines and a
// hostname can be reused. A random value cannot collide by accident, and the
// only property the Endpoint needs is "different database, different value".
func newServerIdentity() (string, error) {
	buffer := make([]byte, 16)
	if _, err := rand.Read(buffer); err != nil {
		return "", fmt.Errorf("generate server identity: %w", err)
	}
	return hex.EncodeToString(buffer), nil
}
