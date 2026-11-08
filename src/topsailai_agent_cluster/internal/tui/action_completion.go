package tui

import (
	"context"
	"sync"
)

// CtlActionCache remembers the advertised control actions per Endpoint.
//
// TAB completion must never perform network I/O: a keystroke handler cannot
// block, and a failed query would silently disable completion. The cache is
// therefore refreshed at prompt time, and only when the Endpoint changed, so one
// scope change costs one capability query instead of one query per keypress.
//
// The cache is opt-in. A REPL that does not supply a completion source performs
// no capability query for completion at all, so the existing contract that a
// capability query happens only when a command needs one is preserved.
//
// A failed query records the Endpoint with an empty list rather than retrying on
// every prompt. Retrying would turn an offline Endpoint into one blocking query
// per typed line, and an empty list is the safe outcome: TAB offers nothing
// instead of offering an action the Endpoint may not support. Re-entering the
// Endpoint scope refreshes the list.
type CtlActionCache struct {
	mu       sync.Mutex
	endpoint string
	names    []string
}

// NewCtlActionCache returns an empty cache. An empty cache completes nothing
// until the first prompt observes an Endpoint.
func NewCtlActionCache() *CtlActionCache {
	return &CtlActionCache{}
}

// Actions returns the advertised control actions for one Endpoint, querying only
// when the Endpoint changed since the last call.
//
// A query failure is not reported to the operator: completion is an aid, not a
// command, so a failed refresh must not turn a typed line into an error. The
// empty list is the visible consequence, and the next scope change retries.
func (c *CtlActionCache) Actions(parent context.Context, api InteractiveAPI, endpointID string) []string {
	c.mu.Lock()
	unchanged := c.endpoint == endpointID
	c.mu.Unlock()
	if unchanged {
		return c.Cached()
	}
	names := []string{}
	if endpointID != "" && api != nil {
		ctx, cancel := commandContext(parent)
		descriptor, err := api.GetCapabilities(ctx, endpointID)
		cancel()
		if err == nil {
			names = ctlActionNames(descriptor)
		}
	}
	c.mu.Lock()
	c.endpoint, c.names = endpointID, names
	c.mu.Unlock()
	return append([]string(nil), names...)
}

// Cached returns a copy of the last observed action names.
//
// The copy keeps the caller from mutating the cache while the REPL rebinds it,
// because completion runs inside the keystroke handler.
func (c *CtlActionCache) Cached() []string {
	c.mu.Lock()
	defer c.mu.Unlock()
	return append([]string(nil), c.names...)
}
