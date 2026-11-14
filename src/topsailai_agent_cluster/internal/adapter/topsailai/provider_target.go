package topsailai

import (
	"context"
	"encoding/base64"
	"encoding/json"
	"errors"
	"fmt"

	"topsailai_agent_cluster/internal/protocol"
)

const sessionRowProviderKeyPrefix = "session-row:"

// providerSessionTarget is the TopsailAI-private selector for one workspace row.
// It never crosses the adapter boundary: the cluster routes by its opaque
// resource ID, while this value is only decoded after that ID reaches Endpoint.
type providerSessionTarget struct {
	SessionID      string `json:"session_id"`
	ProviderRowKey string `json:"provider_row_key,omitempty"`
	PID            int64  `json:"pid,omitempty"`
	IsTask         bool   `json:"is_task,omitempty"`
	// SessionScoped marks a mapping that names the session and nothing else.
	// It is declared rather than inferred from empty fields, because an empty
	// row key is also what a provider row legitimately reports when it has no
	// filename, and inferring would silently change how an existing row mapping
	// is matched. A session-scoped mapping is minted when an operator names a
	// session by the provider's own identifier, before any row is known.
	SessionScoped bool `json:"session_scoped,omitempty"`
}

// providerSessionKey encodes one provider row into the durable adapter mapping
// key without exposing the representation as a cluster identity.
func providerSessionKey(item workspaceItem) (string, error) {
	target := providerSessionTarget{SessionID: item.SessionID, ProviderRowKey: item.ProviderRowKey, PID: item.PID, IsTask: item.IsTask}
	document, err := json.Marshal(target)
	if err != nil {
		return "", fmt.Errorf("encode provider session target: %w", err)
	}
	return sessionRowProviderKeyPrefix + base64.RawURLEncoding.EncodeToString(document), nil
}

// decodeProviderSessionKey restores the private selector stored in the mapping.
func decodeProviderSessionKey(key string) (providerSessionTarget, error) {
	if len(key) <= len(sessionRowProviderKeyPrefix) || key[:len(sessionRowProviderKeyPrefix)] != sessionRowProviderKeyPrefix {
		return providerSessionTarget{}, errors.New("resource mapping is not a TopsailAI session row")
	}
	document, err := base64.RawURLEncoding.DecodeString(key[len(sessionRowProviderKeyPrefix):])
	if err != nil {
		return providerSessionTarget{}, fmt.Errorf("decode provider session mapping: %w", err)
	}
	var target providerSessionTarget
	if err := json.Unmarshal(document, &target); err != nil {
		return providerSessionTarget{}, fmt.Errorf("decode provider session target: %w", err)
	}
	if target.SessionID == "" {
		return providerSessionTarget{}, errors.New("provider session target has no session ID")
	}
	return target, nil
}

// providerSessionTarget resolves one opaque public resource to its adapter-private
// provider selectors while preserving caller cancellation.
func (a *Adapter) providerSessionTarget(ctx context.Context, target *protocol.CommandTarget) (providerSessionTarget, error) {
	if target == nil {
		return providerSessionTarget{}, errors.New("target is required")
	}
	if a.mapper == nil {
		return providerSessionTarget{}, errors.New("durable resource mapper is required")
	}
	mapping, err := a.mapper.LookupResourceID(ctx, target.ResourceID)
	if err != nil {
		return providerSessionTarget{}, err
	}
	return decodeProviderSessionKey(mapping.ProviderKey)
}

// providerTarget returns the provider's session selector for operations whose
// public provider command is session-scoped.
func (a *Adapter) providerTarget(ctx context.Context, target *protocol.CommandTarget) (string, error) {
	resolved, err := a.providerSessionTarget(ctx, target)
	if err != nil {
		return "", err
	}
	return resolved.SessionID, nil
}

// matchesWorkspaceItem reports whether a fresh provider row is the exact row
// represented by a durable mapping.
//
// A session-scoped mapping names the session and nothing else, so it matches any
// row of that session. That is the correct reading for a target the operator
// named by session identifier: the operator did not choose a row, and one
// provider session identifier can appear in several rows. Matching only the
// session is also what keeps the liveness gate honest, because Inspect scans
// every row of the session and reports Live when any of them is live.
func (target providerSessionTarget) matchesWorkspaceItem(item workspaceItem) bool {
	if target.SessionScoped {
		return item.SessionID == target.SessionID
	}
	return item.SessionID == target.SessionID && item.ProviderRowKey == target.ProviderRowKey && item.PID == target.PID && item.IsTask == target.IsTask
}

// runtimeLogArgs builds the provider's supported row-specific log selector.
func runtimeLogArgs(target providerSessionTarget, lines int, follow bool) []string {
	args := []string{"runtime", "logs", "-s", target.SessionID}
	if target.PID > 0 {
		args = append(args, "-p", fmt.Sprint(target.PID))
	}
	if target.IsTask {
		args = append(args, "--is-task")
	}
	args = append(args, "-n", fmt.Sprint(lines))
	if follow {
		return append(args, "--follow")
	}
	return append(args, "--json")
}
