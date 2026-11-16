package adapter

import (
	"context"

	"topsailai_agent_cluster/internal/protocol"
)

// DetailHandler optionally reads one session's provider metadata and runtime
// document.
//
// It mirrors MessagesHandler: an adapter that cannot read a session record simply
// does not implement it, and the Endpoint reports the capability as absent rather
// than returning an empty document. An empty document would read as "this provider
// keeps no record for the session", which is a different claim from "this adapter
// cannot answer".
//
// The record is provider detail, so the adapter forwards it rather than translating
// it. The cluster does not model a provider's session record, and an adapter that
// translated it into cluster fields would have to change whenever the provider did.
//
// The runtime document is a seam. An adapter that has nothing to report leaves it
// empty, and the surface says it was not reported. Filling it later is an adapter
// change only, because every layer already carries the field.
type DetailHandler interface {
	Detail(context.Context, protocol.SessionDetailQuery) (protocol.SessionDetail, error)
}
