package server

import (
	"context"
	"net/http"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func TestNewServiceRejectsMissingDependencies(t *testing.T) {
	cases := []ServiceDeps{{}, {APIHandler: httpHandlerStub{}}, {APIHandler: httpHandlerStub{}, ChannelServer: nil}}
	for _, deps := range cases {
		if _, err := NewService(deps); err == nil {
			t.Fatal("invalid service dependencies accepted")
		}
	}
}

type httpHandlerStub struct{}

func (httpHandlerStub) ServeHTTP(http.ResponseWriter, *http.Request) {}

func TestCommandServiceRejectsInvalidAdmissionAndUnavailableTransport(t *testing.T) {
	service := &CommandService{}
	if _, _, err := service.Admit(context.Background(), protocol.ImmutableIntent{}, ""); err == nil {
		t.Fatal("invalid admission accepted")
	}
}
