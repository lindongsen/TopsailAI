package adapter

import (
	"context"

	"topsailai_agent_cluster/internal/protocol"
)

// ModelCatalogHandler optionally lists the model profiles a session can select.
//
// It mirrors HistoryHandler: an adapter that cannot list model profiles simply
// does not implement it, and the Endpoint reports the capability as absent rather
// than returning an empty catalog. An empty catalog would read as "this session
// offers no selectable profile", which is a different claim from "this adapter
// cannot answer".
//
// The adapter owns the mapping from its provider's own model entries onto opaque
// cluster profile identifiers, because it is the only layer that knows how the
// provider stores them. The cluster never learns a provider name, index or path,
// and the Server never interprets one.
type ModelCatalogHandler interface {
	ModelCatalog(context.Context, protocol.ModelCatalogQuery) (protocol.ModelCatalog, error)
}
