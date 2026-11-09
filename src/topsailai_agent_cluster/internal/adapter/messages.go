package adapter

import (
	"context"

	"topsailai_agent_cluster/internal/protocol"
)

// MessagesHandler optionally reads one session's conversation without mutation.
//
// It mirrors HistoryHandler: an adapter that cannot read messages simply does not
// implement it, and the Endpoint reports the capability as absent rather than
// returning an empty list. An empty list would read as "this session recorded no
// messages", which is a different claim from "this adapter cannot answer".
//
// Messages are persisted provider data, so this method needs no generation and no
// liveness check. It is the only read path that treats a running session and a
// stopped session identically, which is why it exists: every other read surface
// requires a live target.
type MessagesHandler interface {
	Messages(context.Context, protocol.MessagesQuery) (protocol.MessagesResult, error)
}
