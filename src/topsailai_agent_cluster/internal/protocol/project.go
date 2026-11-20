package protocol

import (
	"fmt"
	"strings"
	"unicode"
)

// ProjectCatalogQuery is intentionally empty: the catalog addresses one
// Endpoint, not one resource, and the frame already names that Endpoint.
type ProjectCatalogQuery struct{}

// ProjectCatalog is one bounded live read of an Endpoint project registry.
type ProjectCatalog struct {
	Projects     []Project `json:"projects"`
	ObservedAtMS int64     `json:"observed_at_ms"`
	Truncated    bool      `json:"truncated"`
	ErrorCode    string    `json:"error_code,omitempty"`
}

// Stable project-catalog failure codes.
const (
	ProjectCatalogUnsupported   = "project_catalog_unsupported"
	ProjectCatalogProviderError = "provider_error"
	ProjectCatalogTooLarge      = "project_catalog_too_large"
)

// Stable project registration failure codes.
//
// The confinement codes are separate from the provider codes because the remedy
// differs: a confinement refusal is a request the operator must correct, while a
// provider failure is a machine condition the operator must investigate.
const (
	ProjectRootUnconfigured    = "project_root_unconfigured"
	ProjectPathOutsideRoot     = "project_path_outside_root"
	ProjectPathNotDirectory    = "project_path_not_directory"
	ProjectFolderInvalid       = "project_folder_invalid"
	ProjectAlreadyRegistered   = "project_already_registered"
	ProjectNotFound            = "project_not_found"
	ProjectRegistryWriteFailed = "project_registry_write_failed"
)

// ProjectAddPayload registers one provider-managed project directory.
//
// Folder is an absolute path that must resolve inside the Endpoint-local project
// root. Name is an optional operator label; an empty name leaves the provider's
// own default in force. Neither field is Cluster authority: the Endpoint mints
// the project identity after the provider reports the registered row.
type ProjectAddPayload struct {
	Folder string `json:"folder"`
	Name   string `json:"name,omitempty"`
}

// Validate checks one project.add payload.
//
// The folder must be an absolute path, because a relative path would resolve
// against the process working directory, which is a location the operator never
// selected. Whitespace and control characters are rejected for the same reason
// they are rejected in agent.start: the value becomes one argv element, and a
// value that looks different from what was typed would register a different
// directory than the operator named.
func (p ProjectAddPayload) Validate() error {
	if strings.TrimSpace(p.Folder) == "" {
		return fmt.Errorf("project.add folder is required")
	}
	if strings.TrimSpace(p.Folder) != p.Folder {
		return fmt.Errorf("project.add folder must not have leading or trailing whitespace")
	}
	if !strings.HasPrefix(p.Folder, "/") {
		return fmt.Errorf("project.add folder must be an absolute path")
	}
	for _, character := range p.Folder {
		if unicode.IsControl(character) {
			return fmt.Errorf("project.add folder must not contain control characters")
		}
	}
	if strings.TrimSpace(p.Name) != p.Name {
		return fmt.Errorf("project.add name must not have leading or trailing whitespace")
	}
	for _, character := range p.Name {
		if unicode.IsControl(character) {
			return fmt.Errorf("project.add name must not contain control characters")
		}
	}
	return nil
}

// ProjectRemovePayload is intentionally empty: the target carries the identity.
type ProjectRemovePayload struct{}
