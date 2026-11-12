package providercli

// StandardQuery describes one registered read-only Provider CLI query.
type StandardQuery struct {
	Name    string
	Version string
}

var standardQueries = []StandardQuery{
	{Name: QueryLaunchOptions, Version: "v1"},
	{Name: QueryHistoryMessages, Version: "v1"},
	{Name: QueryModelCatalog, Version: "v1"},
	{Name: QuerySessionMessages, Version: "v1"},
}

// StandardQueries returns a detached copy of the closed query registry.
func StandardQueries() []StandardQuery {
	queries := make([]StandardQuery, len(standardQueries))
	copy(queries, standardQueries)
	return queries
}

// IsStandardQuery reports whether a query name and version are registered.
func IsStandardQuery(name, version string) bool {
	for _, query := range standardQueries {
		if query.Name == name && query.Version == version {
			return true
		}
	}
	return false
}
