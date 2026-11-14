package topsailai

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"topsailai_agent_cluster/internal/adapter"
)

// providerSessionHandleKey encodes a session-scoped mapping key from a provider
// session identifier alone.
//
// It is deliberately distinct from providerSessionKey, which encodes one
// workspace row. A row key carries the row key, PID and task flag, because one
// provider session identifier can appear in several independently selectable
// rows. A handle names the session and nothing else, so its mapping must be
// session-scoped: it cannot claim to be one particular row, and it must not
// pretend to know a PID or a task flag it was never told.
//
// The prefix is shared with the row key on purpose. Both are TopsailAI session
// selectors, so decodeProviderSessionKey accepts both, and the difference is
// carried by the declared SessionScoped flag rather than by a second prefix that
// every decoder would have to learn.
func providerSessionHandleKey(sessionID string) (string, error) {
	if sessionID == "" {
		return "", errors.New("provider session handle is empty")
	}
	target := providerSessionTarget{SessionID: sessionID, SessionScoped: true}
	document, err := json.Marshal(target)
	if err != nil {
		return "", fmt.Errorf("encode provider session handle: %w", err)
	}
	return sessionRowProviderKeyPrefix + base64.RawURLEncoding.EncodeToString(document), nil
}

// ResolveProviderSessionHandle mints the durable mapping for a session the
// operator named by the provider's own identifier.
//
// It never asks the provider whether the session exists. The operator named the
// target, so deciding existence here would reject exactly the case this path
// exists for: a session the Endpoint has not discovered yet, or one whose record
// the provider still lists while no process holds it. Minting is local
// bookkeeping, and the provider remains the only party that can answer whether
// the session is real when the operation actually reaches it.
//
// The mapping is minted through the same durable mapper discovery uses, so the
// resource ID is stable: resolving the same handle twice returns the same ID, and
// a later discovery of that session reuses it instead of minting a second
// identity for one session.
func (a *Adapter) ResolveProviderSessionHandle(ctx context.Context, handle string) (adapter.ResourceMapping, error) {
	if a.mapper == nil {
		return adapter.ResourceMapping{}, errors.New("durable resource mapper is required")
	}
	providerKey, err := providerSessionHandleKey(handle)
	if err != nil {
		return adapter.ResourceMapping{}, err
	}
	return a.mapper.GetOrCreateResourceID(ctx, a.config.AdapterID, providerKey, time.Now().UnixMilli())
}
