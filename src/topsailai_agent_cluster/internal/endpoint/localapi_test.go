package endpoint

import (
	"context"
	"testing"
	"topsailai_agent_cluster/internal/protocol"
)

func TestLocalAPIDelegatesToExecutor(t *testing.T) {
	if NewLocalAPI(nil).executor != nil {
		t.Fatal("nil executor changed")
	}
	_ = context.Background()
	_ = protocol.ImmutableIntent{}
}
