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

// ModelRegistryHandler optionally lists the models one Endpoint offers to launches.
//
// It is a separate interface from ModelCatalogHandler rather than a second method on
// it, because the two answer different questions about different subjects. A catalog
// is addressed by a session and answers what that session can select; a registry is
// addressed by the machine and answers what a launch from it would use. An adapter
// that can answer one and not the other is a real configuration, so the Endpoint must
// be able to report the two capabilities independently.
//
// The adapter owns the mapping from its provider's own model entries onto opaque
// cluster profile identifiers, because it is the only layer that knows how the
// provider stores them. The provider's identifier travels inside the adapter so it can
// mark which entry the provider selected, and it never reaches the wire.
type ModelRegistryHandler interface {
	ModelRegistry(context.Context, protocol.ModelRegistryQuery) (protocol.ModelRegistry, error)
}
