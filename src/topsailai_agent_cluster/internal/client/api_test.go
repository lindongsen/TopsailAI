package client

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

func TestAPIClientMethodsAndErrors(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer token" {
			http.Error(w, `{"message":"unauthorized"}`, http.StatusUnauthorized)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		if strings.HasSuffix(r.URL.Path, "/missing") {
			w.WriteHeader(http.StatusNotFound)
			_, _ = fmt.Fprint(w, `{"code":"not_found","message":"missing","data":null}`)
			return
		}
		data := `null`
		switch {
		case r.URL.Path == "/api/v1/endpoints":
			data = `[{"endpoint_id":"e1"}]`
		case strings.HasSuffix(r.URL.Path, "/session-state"):
			data = `{"schema_version":"v1"}`
		case strings.HasSuffix(r.URL.Path, "/capabilities"):
			data = `{"revision":"v1"}`
		case r.URL.Path == "/api/v1/commands" && r.Method == http.MethodGet:
			data = `[{"command_id":"c1"}]`
		case strings.HasPrefix(r.URL.Path, "/api/v1/commands/"):
			data = `{"command_id":"c1"}`
		case r.URL.Path == "/api/v1/commands" && r.Method == http.MethodPost:
			data = `{"command_id":"c1"}`
		case r.URL.Path == "/api/v1/output":
			data = `{"data":"ok"}`
		}
		_, _ = fmt.Fprintf(w, `{"code":0,"message":"ok","data":%s}`, data)
	}))
	defer server.Close()
	client := NewAPIClient(server.URL, "token")
	ctx := context.Background()
	if endpoints, err := client.ListEndpoints(ctx); err != nil || len(endpoints) != 1 || endpoints[0].EndpointID != "e1" {
		t.Fatalf("ListEndpoints=%#v err=%v", endpoints, err)
	}
	if _, err := client.GetInventory(ctx, "e1"); err != nil {
		t.Fatal(err)
	}
	if _, err := client.GetCapabilities(ctx, "e1"); err != nil {
		t.Fatal(err)
	}
	if _, err := client.GetCommand(ctx, "c1"); err != nil {
		t.Fatal(err)
	}
	if _, err := client.ListCommands(ctx, "e1", "res_1", 2); err != nil {
		t.Fatal(err)
	}
	if _, err := client.GetOutput(ctx, "e1", "res_1", "g1", 10); err != nil {
		t.Fatal(err)
	}
	intent := protocol.ImmutableIntent{CommandID: "c1", EndpointID: "e1", Operation: "send"}
	if _, err := client.AdmitCommand(ctx, intent); err != nil {
		t.Fatal(err)
	}
	if _, err := client.CancelCommand(ctx, "c1"); err != nil {
		t.Fatal(err)
	}
	bad := NewAPIClient(server.URL, "wrong")
	if _, err := bad.GetCommand(ctx, "missing"); err == nil {
		t.Fatal("unauthorized request succeeded")
	}
}

func TestAPIClientRequestDecodeAndTransportErrors(t *testing.T) {
	client := NewAPIClient("http://[::1", "")
	if _, err := client.GetCommand(context.Background(), "c1"); err == nil {
		t.Fatal("invalid URL succeeded")
	}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = fmt.Fprint(w, "not-json")
	}))
	client = NewAPIClient(server.URL, "")
	server.Close()
	if _, err := client.GetCommand(context.Background(), "c1"); err == nil {
		t.Fatal("transport failure succeeded")
	}
}
