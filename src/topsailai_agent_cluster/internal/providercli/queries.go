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
	{Name: QuerySessionMetrics, Version: "v1"},
	{Name: QuerySessionDetail, Version: "v1"},
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

// QueryRequiresSessionTarget reports whether one registered query addresses a
// session and therefore must carry a session target.
//
// The rule is stated once, here, because two callers need it for different
// reasons: DecodeQueryPayload rejects a request that breaks it, and the
// conformance suite builds a request that satisfies it. A second copy in the
// suite would let a newly registered session-scoped query be exercised with no
// target, and the resulting failure would read as a Provider defect rather than
// as a gap in the test.
func QueryRequiresSessionTarget(name string) bool {
	switch name {
	case QueryModelCatalog, QuerySessionMessages, QuerySessionMetrics, QuerySessionDetail:
		return true
	default:
		return false
	}
}
