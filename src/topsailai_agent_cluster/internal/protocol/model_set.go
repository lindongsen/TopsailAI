package protocol

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

// ModelSetPayload declares which model a launch from one Endpoint should use.
//
// It carries exactly one opaque Cluster profile identifier and nothing else. The
// payload is the only place a caller could try to smuggle provider vocabulary onto
// the wire: a provider model name, a provider index or a provider file path would
// otherwise travel as an extra key and be forwarded verbatim by an adapter that
// decodes loosely. Unknown fields are rejected for that reason, so the Server
// validates a standard document and never forwards provider vocabulary.
//
// The identifier is the same opaque value ModelRegistryEntry reports, so a caller
// that just rendered a registry can name a row without learning anything about how
// the provider stores it.
type ModelSetPayload struct {
	ModelProfileID string `json:"model_profile_id"`
}

// ValidateModelSetPayload validates the standard payload of agent.model.set.
//
// The checks are the ones the Endpoint depends on before it resolves the identifier:
// a non-empty value, a bounded length, and no surrounding whitespace. Whitespace is
// rejected rather than trimmed because trimming would silently change which profile
// the caller named, and an identifier is an identity rather than a label.
func ValidateModelSetPayload(payload []byte) (ModelSetPayload, error) {
	var request ModelSetPayload
	decoder := json.NewDecoder(bytes.NewReader(payload))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&request); err != nil {
		return ModelSetPayload{}, fmt.Errorf("decode model set payload: %w", err)
	}
	if strings.TrimSpace(request.ModelProfileID) == "" {
		return ModelSetPayload{}, errors.New("model_profile_id is required")
	}
	if strings.TrimSpace(request.ModelProfileID) != request.ModelProfileID {
		return ModelSetPayload{}, errors.New("model_profile_id must not have leading or trailing whitespace")
	}
	if len(request.ModelProfileID) > MaxModelProfileIDBytes {
		return ModelSetPayload{}, fmt.Errorf("model_profile_id exceeds %d bytes", MaxModelProfileIDBytes)
	}
	return request, nil
}

// Standard model-set error codes.
//
// They are provider-neutral: an adapter maps its own vocabulary onto these values
// and keeps provider detail local. Each code names a different remedy, which is why
// they are not collapsed into one failure value.
const (
	// ModelSetUnknownProfile means the requested identifier is not one this
	// Endpoint minted. It is rejected before any provider call, so an unknown
	// identifier can never reach a provider as a guess.
	ModelSetUnknownProfile = "unknown_model_profile"
	// ModelSetUnavailable means the profile exists but cannot be selected now,
	// such as an entry the provider reports as disabled. The remedy is to choose
	// another profile, not to investigate a fault.
	ModelSetUnavailable = "model_profile_unavailable"
	// ModelSetUnsupported means no configured adapter can change the environment
	// model. It is reported instead of a silent success, because a caller that
	// believes a declaration changed would launch with the wrong model.
	ModelSetUnsupported = "model_set_unsupported"
	// ModelSetProviderError means the adapter's provider call failed.
	ModelSetProviderError = "provider_error"
)

// ModelSetPayloadVersion is the payload schema version of agent.model.set.
const ModelSetPayloadVersion = "1"
