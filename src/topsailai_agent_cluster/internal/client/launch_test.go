package client

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
)

// TestLaunchClientSelectors verifies public query encoding and parsed results.
func TestLaunchClientSelectors(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Query().Get("endpoint_id") != "e /" || r.URL.Query().Get("adapter_id") != "a&1" {
			t.Error(r.URL)
		}
		fmt.Fprint(w, `{"code":0,"data":{"handlers":[{"adapter_id":"a&1","revision":"v"}],"projects":[]}}`)
	}))
	defer server.Close()
	result, err := NewAPIClient(server.URL, "").GetLaunchOptions(context.Background(), "e /", "a&1")
	if err != nil || len(result.Handlers) != 1 {
		t.Fatalf("%#v %v", result, err)
	}
}
