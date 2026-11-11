package node

import (
	"sync/atomic"

	"topsailai_connector/internal/security"
)

// IdentityHolder holds the identity the Node is currently serving under.
//
// The identity is not a constant for the life of the process: `connector-node
// regenerate` rewrites the identity file while the Node keeps running, and the
// running process must adopt the new pair. A holder is used instead of a plain
// field because the value is read on every request and written by the watcher, so
// a plain field would be a data race that the race detector reports and a torn
// read that it does not.
//
// The holder stores a pointer rather than a value, so a reader never observes a
// half-written identity: the swap is one atomic store of a fully built value.
type IdentityHolder struct {
	current atomic.Pointer[security.NodeIdentity]
}

// NewIdentityHolder returns a holder serving the given identity.
func NewIdentityHolder(identity security.NodeIdentity) *IdentityHolder {
	holder := &IdentityHolder{}
	stored := identity
	holder.current.Store(&stored)
	return holder
}

// Current returns the identity the Node is serving under.
//
// A nil holder returns the zero identity rather than panicking, because a
// dispatcher built without an identity must refuse every request instead of
// crashing on the request path. The zero identity matches no request, so the
// refusal is the default-deny answer the design requires.
func (h *IdentityHolder) Current() security.NodeIdentity {
	if h == nil {
		return security.NodeIdentity{}
	}
	stored := h.current.Load()
	if stored == nil {
		return security.NodeIdentity{}
	}
	return *stored
}

// Replace installs a new identity and reports whether it differs from the one
// already held.
//
// The comparison covers both halves: a regeneration that keeps the identifier
// still changes the token, and a token change is what invalidates the previous
// credential. Reporting "unchanged" for an identical pair keeps the watcher from
// dropping a working channel on every poll.
func (h *IdentityHolder) Replace(identity security.NodeIdentity) bool {
	if h == nil {
		return false
	}
	current := h.Current()
	if current.ID == identity.ID && current.Token.Equal(identity.Token) {
		return false
	}
	stored := identity
	h.current.Store(&stored)
	return true
}
