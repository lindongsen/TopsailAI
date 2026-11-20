package protocol

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
