package topsailai

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
	"time"
	"unicode/utf8"

	"topsailai_agent_cluster/internal/protocol"
)

// modelRegistryEntry mirrors one record of the provider's `models list --json`
// document.
//
// The provider emits more fields than these, including a base URL, environment
// variable names and free-form metadata. None of them are consumed: a profile is
// an operator-facing menu entry, and the rest is provider configuration the
// cluster must never carry, log or forward.
type modelRegistryEntry struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	Protocol string `json:"protocol"`
	// Enabled is a pointer because the provider omits the field when the entry is
	// enabled and emits it only when the entry is disabled. A plain bool would
	// therefore read an omitted field as "disabled", which would mark every
	// healthy profile unavailable.
	Enabled *bool `json:"enabled"`
}

// providerSupportedProtocol is the only protocol this provider can run.
//
// The provider rejects any other value when it builds the model environment, so a
// profile carrying one is reported as unavailable instead of being offered and
// then failing at selection time.
const providerSupportedProtocol = "openai-compatible"

// ModelCatalog lists the model profiles one session can select.
//
// The read is deliberately session-scoped even though the provider's registry is
// per provider home rather than per session: the target is what proves the caller
// addressed a session this Endpoint knows, and it is the same addressing every
// other session-scoped operation uses. The registry itself is not read from disk
// here, because the provider owns that file and its location.
//
// The provider applies no cap to `models list`, so a returned catalog is complete
// as far as the provider reports it and Truncated stays false. One limitation is
// recorded rather than papered over: the provider skips a malformed registry line
// and warns on stderr, and this adapter captures stdout only, so a skipped line is
// invisible here. Reporting Truncated unconditionally would be worse, because a
// flag that is always set stops being read.
func (a *Adapter) ModelCatalog(ctx context.Context, query protocol.ModelCatalogQuery) (protocol.ModelCatalog, error) {
	if query.Target.Kind != "session" {
		return protocol.ModelCatalog{}, fmt.Errorf("model catalog requires a session target")
	}
	providerKey, err := a.providerTarget(ctx, &query.Target)
	if err != nil {
		return protocol.ModelCatalog{}, err
	}
	// A model profile identifier lives in the same mapping table as a session key,
	// so a caller that passed a profile identifier as the target would otherwise
	// resolve successfully and be treated as a session. The prefix check rejects
	// that instead of listing profiles for a resource that is not a session.
	if strings.HasPrefix(providerKey, modelProviderKeyPrefix) {
		return protocol.ModelCatalog{}, fmt.Errorf("model catalog requires a session target")
	}
	output, err := a.run(ctx, []string{"models", "list", "--json"}, nil)
	if err != nil {
		return protocol.ModelCatalog{ErrorCode: protocol.ModelCatalogProviderError}, err
	}
	if len(output) > protocol.MaxModelCatalogBytes {
		return protocol.ModelCatalog{ErrorCode: protocol.ModelCatalogTooLarge}, fmt.Errorf("model catalog exceeds byte limit")
	}
	var entries []modelRegistryEntry
	if err := json.Unmarshal(output, &entries); err != nil {
		return protocol.ModelCatalog{ErrorCode: protocol.ModelCatalogProviderError}, fmt.Errorf("decode model catalog: %w", err)
	}
	if len(entries) > protocol.MaxModelProfiles {
		return protocol.ModelCatalog{ErrorCode: protocol.ModelCatalogTooLarge}, fmt.Errorf("model profile count exceeds limit")
	}
	entries = collapseModelEntriesByName(entries)
	nowMS := time.Now().UnixMilli()
	result := protocol.ModelCatalog{Profiles: make([]protocol.ModelProfile, 0, len(entries)), ObservedAtMS: nowMS}
	for _, entry := range entries {
		// The provider selects a model by name, so an entry without one cannot be
		// selected at all. Publishing it would offer the operator a row that fails
		// at dispatch, which is worse than omitting it.
		if entry.Name == "" {
			continue
		}
		// The opaque identifier is minted from the provider name, because the name
		// is the provider's own selection key. Minting from the registry id would
		// produce an identifier that resolves to a name the provider never accepts.
		profileID, err := a.resourceID(ctx, modelProviderKeyPrefix+entry.Name)
		if err != nil {
			return protocol.ModelCatalog{}, fmt.Errorf("map model profile: %w", err)
		}
		available, reason := modelProfileAvailability(entry)
		result.Profiles = append(result.Profiles, protocol.ModelProfile{
			ModelProfileID:    profileID,
			DisplayName:       boundedModelDisplayName(entry.Name),
			Available:         available,
			UnavailableReason: reason,
		})
	}
	return result, nil
}

// collapseModelEntriesByName keeps one entry per provider name.
//
// The provider rejects a duplicate registry id but silently collapses a duplicate
// name, because it builds a name-keyed map where the last entry wins while the
// first entry's position is kept. Minting one identifier per name would otherwise
// publish the same identifier twice, so the catalog would show two rows that
// select the same thing. Collapsing here reproduces the provider's own resolution,
// so the catalog lists exactly what the provider can actually select.
func collapseModelEntriesByName(entries []modelRegistryEntry) []modelRegistryEntry {
	positions := make(map[string]int, len(entries))
	collapsed := make([]modelRegistryEntry, 0, len(entries))
	for _, entry := range entries {
		if entry.Name == "" {
			collapsed = append(collapsed, entry)
			continue
		}
		if position, seen := positions[entry.Name]; seen {
			collapsed[position] = entry
			continue
		}
		positions[entry.Name] = len(collapsed)
		collapsed = append(collapsed, entry)
	}
	return collapsed
}

// modelProfileAvailability reports whether one entry can be selected now.
//
// A disabled entry and an entry whose protocol the provider cannot run are both
// reported as unavailable with a standard reason code, and both stay in the
// catalog. Dropping them would hide a configuration the operator may need to fix,
// and the operator cannot repair what the menu does not show.
func modelProfileAvailability(entry modelRegistryEntry) (bool, string) {
	if entry.Enabled != nil && !*entry.Enabled {
		return false, protocol.ModelProfileDisabled
	}
	if entry.Protocol != providerSupportedProtocol {
		return false, protocol.ModelProfileUnsupportedProtocol
	}
	return true, ""
}

// boundedModelDisplayName keeps one display name inside the accepted bound.
//
// The name is truncated rather than dropped, because the profile is still
// selectable and the operator needs to see that it exists. The cut lands on a
// UTF-8 boundary so a multi-byte name is never published as half a character.
func boundedModelDisplayName(name string) string {
	if !utf8.ValidString(name) {
		return ""
	}
	if len(name) <= protocol.MaxModelDisplayNameBytes {
		return name
	}
	cut := protocol.MaxModelDisplayNameBytes
	for cut > 0 && !utf8.RuneStart(name[cut]) {
		cut--
	}
	return name[:cut]
}
