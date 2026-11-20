package protocol

import (
	"fmt"
	"strings"
)

// ModelRegistryQuery is intentionally empty: the registry addresses one Endpoint,
// not one resource, and the frame already names that Endpoint.
//
// It is a separate query from ModelCatalogQuery rather than a catalog read with an
// optional target, because the two answer different questions. A catalog answers
// "which profiles can this session select", and a session is the subject. A
// registry answers "which profiles does this machine offer, and which one would a
// launch use", and the machine is the subject. Giving one query two subjects would
// make an empty target mean "the whole machine", so a caller that forgot the target
// would silently receive a different answer instead of a refusal.
type ModelRegistryQuery struct{}

// ModelRegistryEntry is one model configuration an Endpoint offers to launches.
//
// It is an Endpoint-scoped opaque resource, exactly like ModelProfile and Project:
// the cluster mints ModelProfileID and the provider's own identifier never appears
// on the wire. The provider's identifier is deliberately not forwarded even though
// the provider reports one, because a provider identifier is provider vocabulary
// and a second provider would supply a different one.
type ModelRegistryEntry struct {
	// ModelProfileID is the opaque cluster identifier the Endpoint minted for this
	// provider entry. It is the only addressing key a caller may use.
	ModelProfileID string `json:"model_profile_id"`
	// ProviderDisplayName is the provider's own label, descriptive only. It is
	// never an addressing key, because a label is chosen for a human and can be
	// renamed without the entry changing identity.
	ProviderDisplayName string `json:"provider_display_name,omitempty"`
	// Available reports whether a launch could use this entry right now.
	Available bool `json:"available"`
	// UnavailableReason is a bounded standard reason code when Available is false.
	UnavailableReason string `json:"unavailable_reason,omitempty"`
}

// ModelRegistry is one bounded read of the models an Endpoint offers to launches.
//
// An empty Entries list is a real answer meaning "this machine has no model
// configured". It is deliberately different from an Endpoint that cannot answer at
// all, which reports ModelRegistryUnsupported instead. Collapsing the two would make
// an unconfigured adapter look like a machine with no models.
type ModelRegistry struct {
	Entries []ModelRegistryEntry `json:"entries"`
	// CurrentProfileID names the profile a launch from this machine would use now.
	// It is empty when no entry is marked selected, which is an observation and not
	// an error: the machine may list usable models while declaring no default.
	CurrentProfileID string `json:"current_profile_id,omitempty"`
	// CurrentSource reports which declaration produced CurrentProfileID. It is a
	// closed vocabulary, because "the machine uses X" is ambiguous on a machine
	// that resolves a model per project folder: the same machine can use different
	// models in different folders, so a caller must be able to tell a machine-wide
	// default from a folder-specific override.
	CurrentSource string `json:"current_source"`
	// ProjectOverrides lists the folder-specific declarations that differ from the
	// machine default. It is reported rather than folded into CurrentProfileID,
	// because folding would state one value for a machine that has several.
	ProjectOverrides []ModelProjectOverride `json:"project_overrides,omitempty"`
	// ObservedAtMS is when the Endpoint observed this registry, in UTC epoch
	// milliseconds. A registry is a live read, so it is never a stored projection.
	ObservedAtMS int64 `json:"observed_at_ms"`
	// Truncated reports that the provider returned its own capped window rather
	// than every entry that exists, so a bounded window is never presented as a
	// complete registry.
	Truncated bool `json:"truncated,omitempty"`
	// ErrorCode is a bounded standard error code when the read could not answer.
	ErrorCode string `json:"error_code,omitempty"`
}

// ModelProjectOverride is one folder-specific model declaration.
//
// The folder is reported because it is the only thing that makes the override
// meaningful: an override without its folder would say "somewhere on this machine a
// different model is used", which an operator cannot act on.
type ModelProjectOverride struct {
	// ProjectWorkspace is the provider's own folder path for the override. It is
	// descriptive evidence, not Cluster authority, and it is never used to address
	// a resource.
	ProjectWorkspace string `json:"project_workspace"`
	// ModelProfileID is the opaque cluster identifier of the declared entry. It is
	// empty when the declaration names an entry the registry does not contain,
	// which is reported rather than hidden: a stale declaration is a fact the
	// operator must see, and inventing an identifier for it would make a missing
	// entry look present.
	ModelProfileID string `json:"model_profile_id,omitempty"`
}

// Standard model-registry error codes. They are provider-neutral: an adapter maps
// its own vocabulary onto these values and keeps provider detail local.
const (
	// ModelRegistryUnsupported means no configured adapter can answer this query.
	// It is reported instead of an empty registry, because an empty registry would
	// read as "this machine offers no model", which is a different claim.
	ModelRegistryUnsupported = "model_registry_unsupported"
	// ModelRegistryProviderError means the adapter's provider call failed.
	ModelRegistryProviderError = "provider_error"
	// ModelRegistryTooLarge means the provider document exceeded a bound.
	ModelRegistryTooLarge = "model_registry_too_large"
	// ModelRegistrySelectionInvalid means the provider holds a selection that
	// cannot be resolved, such as an entry that was deleted or disabled. It is a
	// distinct code because the remedy differs: the operator must repair the
	// selection, not investigate a provider fault.
	ModelRegistrySelectionInvalid = "model_registry_selection_invalid"
)

// Standard model-registry current-source values. The vocabulary is closed, because
// the value states where a selection came from and a free-form string would let an
// adapter invent a fourth answer the renderer cannot interpret.
const (
	// ModelSourceWorkspace means the machine-wide default produced the selection.
	ModelSourceWorkspace = "workspace"
	// ModelSourceProject means a folder-specific declaration produced it.
	ModelSourceProject = "project"
	// ModelSourceInherited means no declaration exists, so the provider's own
	// inherited default applies. It is a first-class value rather than an absent
	// field: "nobody declared a model" is a fact, while an absent field would read
	// as "nobody looked".
	ModelSourceInherited = "inherited"
	// ModelSourceUnknown means the Endpoint did not observe where the selection
	// came from. It is never a failure and never a definite negative.
	ModelSourceUnknown = "unknown"
)

// ValidateModelSource rejects a source outside the closed vocabulary instead of
// guessing what an unknown value was meant to mean.
func ValidateModelSource(value string) error {
	switch value {
	case ModelSourceWorkspace, ModelSourceProject, ModelSourceInherited, ModelSourceUnknown:
		return nil
	default:
		return fmt.Errorf("invalid model source %q", value)
	}
}

// Bounds for one model registry read. They are deliberately small: a registry is an
// operator-facing menu, not a bulk export.
const (
	// MaxModelRegistryEntries bounds the accepted entry count.
	MaxModelRegistryEntries = 1000
	// MaxModelRegistryBytes bounds the accepted provider document size.
	MaxModelRegistryBytes = 256 << 10
	// MaxModelProjectOverrides bounds the accepted override count. It is a separate
	// bound from the entry count because overrides are a different collection: a
	// machine can have many folders and few models.
	MaxModelProjectOverrides = 1000
)

// ValidateModelRegistry checks one registry document against the contract.
//
// It is called by the Endpoint before the document is published, so a malformed
// provider answer is refused at the boundary that produced it instead of reaching a
// renderer that would have to guess. The checks are the ones a renderer depends on:
// a non-empty identifier, a bounded display name, a closed source vocabulary, and an
// override that names its folder.
func ValidateModelRegistry(registry ModelRegistry) error {
	if len(registry.Entries) > MaxModelRegistryEntries {
		return fmt.Errorf("model registry exceeds %d entries", MaxModelRegistryEntries)
	}
	if len(registry.ProjectOverrides) > MaxModelProjectOverrides {
		return fmt.Errorf("model registry exceeds %d project overrides", MaxModelProjectOverrides)
	}
	if err := ValidateModelSource(registry.CurrentSource); err != nil {
		return err
	}
	seen := make(map[string]struct{}, len(registry.Entries))
	for _, entry := range registry.Entries {
		if strings.TrimSpace(entry.ModelProfileID) == "" {
			return fmt.Errorf("model registry entry has no model_profile_id")
		}
		if len(entry.ModelProfileID) > MaxModelProfileIDBytes {
			return fmt.Errorf("model registry entry model_profile_id exceeds %d bytes", MaxModelProfileIDBytes)
		}
		if len(entry.ProviderDisplayName) > MaxModelDisplayNameBytes {
			return fmt.Errorf("model registry entry display name exceeds %d bytes", MaxModelDisplayNameBytes)
		}
		if _, exists := seen[entry.ModelProfileID]; exists {
			return fmt.Errorf("model registry contains duplicate model_profile_id %q", entry.ModelProfileID)
		}
		seen[entry.ModelProfileID] = struct{}{}
	}
	for _, override := range registry.ProjectOverrides {
		if strings.TrimSpace(override.ProjectWorkspace) == "" {
			return fmt.Errorf("model registry project override has no project_workspace")
		}
	}
	return nil
}
