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
	{Name: QueryProjectCatalog, Version: "v1"},
	{Name: QuerySessionMessages, Version: "v1"},
	{Name: QuerySessionMetrics, Version: "v1"},
	{Name: QuerySessionMetricsBatch, Version: "v1"},
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
	case QuerySessionMetricsBatch:
		// The batch query addresses a set, not one resource, so it carries no
		// target: the set travels in the payload. It is named here rather than
		// left to the default so a reader cannot mistake its absence from the
		// list above for an omission.
		return false
	default:
		return false
	}
}

// QueryRequiresSessionSet reports whether one registered query addresses a set
// of sessions and therefore must carry that set in its payload.
//
// The rule is stated once, here, for the same reason QueryRequiresSessionTarget
// is: DecodeQueryPayload enforces it and the conformance suite builds a request
// that satisfies it. Without a shared rule the suite swept every registered
// query while supplying a payload only for the ones it happened to name, so a
// set-addressed query reached the Provider with an empty payload and the
// Provider's correct rejection read as a Provider defect.
func QueryRequiresSessionSet(name string) bool {
	switch name {
	case QuerySessionMetricsBatch:
		return true
	default:
		return false
	}
}
