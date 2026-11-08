package adapter

import (
	"context"

	"topsailai_agent_cluster/internal/protocol"
)

// HistoryHandler optionally lists provider session history without mutation.
//
// It mirrors ProjectHandler: an adapter that cannot list history simply does not
// implement it, and the Endpoint reports the capability as absent rather than
// returning an empty list. An empty list would read as "this Endpoint has no
// history", which is a different claim from "this adapter cannot answer".
//
// The adapter owns the first-line resumability verdict, because it is the only
// layer that knows what a provider status word means. The cluster does not
// re-derive that verdict, and the provider's own final judgment at dispatch time
// remains authoritative and out of cluster scope.
type HistoryHandler interface {
	History(context.Context, protocol.HistoryQuery) (protocol.HistoryResult, error)
}
