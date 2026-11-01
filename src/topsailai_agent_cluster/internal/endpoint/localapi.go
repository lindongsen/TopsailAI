package endpoint

import (
	"context"

	"topsailai_agent_cluster/internal/protocol"
)

// LocalAPI exposes the controlled Endpoint execution boundary to local callers.
type LocalAPI struct{ executor *Executor }

// NewLocalAPI creates a local API sharing the executor journal and queues.
func NewLocalAPI(executor *Executor) *LocalAPI { return &LocalAPI{executor: executor} }

// Execute submits one standard command through the durable execution path.
func (a *LocalAPI) Execute(ctx context.Context, intent protocol.ImmutableIntent, requestHash string) (protocol.ExecutionReceipt, error) {
	return a.executor.Execute(ctx, intent, requestHash)
}
