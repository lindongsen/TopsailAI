package node

import (
	"sync/atomic"

	"topsailai_connector/internal/security"
)

// IdentityHolder holds the identity the Node is currently serving under.
//
// The identity is two independent values: the public node id the Server routes by,
// and the credential set the Node verifies proofs with. They are held together
// because a request needs both, and they are replaced independently because they
// answer different questions: regenerating the identifier must not revoke a caller,
// and revoking a caller must not change the address.
//
// A holder is used instead of plain fields because both values are read on every
// request and written by the watcher, so a plain field would be a data race that the
// race detector reports and a torn read that it does not. Each value is stored as a
// pointer, so a reader never observes a half-written value: the swap is one atomic
// store of a fully built value.
type IdentityHolder struct {
	nodeID      atomic.Pointer[string]
	credentials atomic.Pointer[security.CredentialSet]
}

// NewIdentityHolder returns a holder serving the given node id and credentials.
func NewIdentityHolder(nodeID string, credentials *security.CredentialSet) *IdentityHolder {
	holder := &IdentityHolder{}
	storedID := nodeID
	holder.nodeID.Store(&storedID)
	holder.credentials.Store(credentials)
	return holder
}

// NodeID returns the public identifier the Node is serving under.
//
// A nil holder returns an empty identifier rather than panicking, because a
// dispatcher built without an identity must refuse every request instead of crashing
// on the request path. The empty identifier matches no request, so the refusal is the
// default-deny answer the design requires.
func (h *IdentityHolder) NodeID() string {
	if h == nil {
		return ""
	}
	stored := h.nodeID.Load()
	if stored == nil {
		return ""
	}
	return *stored
}

// Credentials returns the credential set the Node verifies proofs with.
//
// A nil holder returns nil, and a nil set refuses every lookup. That is the same
// default-deny answer NodeID gives, and it is the reason a lookup on a nil set is
// safe rather than a panic.
func (h *IdentityHolder) Credentials() *security.CredentialSet {
	if h == nil {
		return nil
	}
	return h.credentials.Load()
}

// ReplaceNodeID installs a new identifier and reports whether it differs from the
// one already held.
//
// Reporting "unchanged" for an identical value keeps the watcher from dropping a
// working channel on every poll. The comparison is on the value rather than on the
// file's modification time, because a regenerated identifier has the same byte
// length as the one it replaces and a rewrite can land inside the same
// modification-time tick as the read that produced the current value.
func (h *IdentityHolder) ReplaceNodeID(nodeID string) bool {
	if h == nil {
		return false
	}
	if h.NodeID() == nodeID {
		return false
	}
	stored := nodeID
	h.nodeID.Store(&stored)
	return true
}

// ReplaceCredentials installs a new credential set and reports whether it differs
// from the one already held.
//
// The comparison is on the public key identifiers, because a set deliberately
// exposes no way to read a secret back. Two sets with the same identifiers but
// different secrets are therefore reported as unchanged, which is the correct answer
// for the caller: the channel was authenticated with the identifier, and a secret
// rotation under one identifier is a change the operator makes by restarting the
// Node rather than by editing the file under a running process.
func (h *IdentityHolder) ReplaceCredentials(credentials *security.CredentialSet) bool {
	if h == nil {
		return false
	}
	current := h.Credentials()
	if sameKeyIDs(current, credentials) {
		return false
	}
	h.credentials.Store(credentials)
	return true
}

// sameKeyIDs reports whether two credential sets name the same public identifiers.
func sameKeyIDs(left, right *security.CredentialSet) bool {
	leftIDs := left.KeyIDs()
	rightIDs := right.KeyIDs()
	if len(leftIDs) != len(rightIDs) {
		return false
	}
	for index := range leftIDs {
		if leftIDs[index] != rightIDs[index] {
			return false
		}
	}
	return true
}
