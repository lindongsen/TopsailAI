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
	if _, err := client.GetOutput(ctx, "e1", "res_1", "g1", 10, 250); err != nil {
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

// TestAPIClientGetOutputSendsLineBudget proves the requested line count is
// transmitted, because a line count that never reaches the Server cannot reach
// the provider and silently leaves `logs -n` ineffective.
func TestAPIClientGetOutputSendsLineBudget(t *testing.T) {
	var query string
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		query = r.URL.RawQuery
		w.Header().Set("Content-Type", "application/json")
		_, _ = fmt.Fprint(w, `{"code":0,"message":"ok","data":{"data":"ok"}}`)
	}))
	defer server.Close()
	client := NewAPIClient(server.URL, "")
	if _, err := client.GetOutput(context.Background(), "e1", "res_1", "g1", 4096, 250); err != nil {
		t.Fatal(err)
	}
	for _, want := range []string{"max_bytes=4096", "max_lines=250"} {
		if !strings.Contains(query, want) {
			t.Fatalf("query=%q missing %q", query, want)
		}
	}
}

// TestAPIClientReportsStatusForNonJSONFailure proves a non-JSON failure body is
// reported by status code instead of by the decoder's own error.
//
// A Server that predates a route answers with plain text, so decoding before
// checking the status hid the only useful evidence: the status code. The
// plain-text 404 case is the worst of them, because "404 page not found" begins
// with digits and the decoder therefore reports a Go type name.
func TestAPIClientReportsStatusForNonJSONFailure(t *testing.T) {
	cases := []struct {
		name    string
		status  int
		body    string
		want    []string
		notWant []string
	}{
		{
			name:    "plain text 404 from a server without the route",
			status:  http.StatusNotFound,
			body:    "404 page not found\n",
			want:    []string{"server request failed (404)", "page not found"},
			notWant: []string{"cannot unmarshal", "Go value of type"},
		},
		{
			name:    "plain text 503",
			status:  http.StatusServiceUnavailable,
			body:    "Service Unavailable",
			want:    []string{"server request failed (503)", "Service Unavailable"},
			notWant: []string{"invalid character"},
		},
		{
			name:    "html 502 from a proxy",
			status:  http.StatusBadGateway,
			body:    "<html><body>502 Bad Gateway</body></html>",
			want:    []string{"server request failed (502)", "502 Bad Gateway"},
			notWant: []string{"invalid character"},
		},
		{
			name:   "empty body",
			status: http.StatusInternalServerError,
			body:   "",
			want:   []string{"server request failed (500)", "empty response body"},
		},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
				w.WriteHeader(testCase.status)
				_, _ = fmt.Fprint(w, testCase.body)
			}))
			defer server.Close()
			client := NewAPIClient(server.URL, "")
			_, err := client.ListEndpoints(context.Background())
			if err == nil {
				t.Fatal("non-2xx response succeeded")
			}
			message := err.Error()
			for _, want := range testCase.want {
				if !strings.Contains(message, want) {
					t.Fatalf("error=%q missing %q", message, want)
				}
			}
			for _, notWant := range testCase.notWant {
				if strings.Contains(message, notWant) {
					t.Fatalf("error=%q must not contain %q", message, notWant)
				}
			}
		})
	}
}

// TestAPIClientSurfacesFailureCode proves the stable machine code reaches the
// caller. Without it a caller can only match human-readable message text, which
// changes whenever the wording changes.
func TestAPIClientSurfacesFailureCode(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusNotFound)
		_, _ = fmt.Fprint(w, `{"code":"session_not_found","message":"Session not found: x","data":null}`)
	}))
	defer server.Close()
	client := NewAPIClient(server.URL, "")
	_, err := client.GetMessages(context.Background(), "e1", "x", 0, 0)
	if err == nil {
		t.Fatal("404 response succeeded")
	}
	message := err.Error()
	for _, want := range []string{"server request failed (404)", "session_not_found", "Session not found: x"} {
		if !strings.Contains(message, want) {
			t.Fatalf("error=%q missing %q", message, want)
		}
	}
}

// TestAPIClientFollowReportsStatusForNonJSONFailure proves the follow path shares
// the same failure decoder, so a non-JSON rejection is not reported as a decode
// error there either.
func TestAPIClientFollowReportsStatusForNonJSONFailure(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusNotFound)
		_, _ = fmt.Fprint(w, "404 page not found\n")
	}))
	defer server.Close()
	client := NewAPIClient(server.URL, "")
	_, err := client.FollowOutput(context.Background(), "e1", "res_1", "g1", 4096, 250)
	if err == nil {
		t.Fatal("non-2xx follow succeeded")
	}
	message := err.Error()
	for _, want := range []string{"server follow failed (404)", "page not found"} {
		if !strings.Contains(message, want) {
			t.Fatalf("error=%q missing %q", message, want)
		}
	}
	if strings.Contains(message, "cannot unmarshal") {
		t.Fatalf("error=%q leaked a decoder error", message)
	}
}

// TestAPIClientRejectsNonEnvelopeSuccess proves a 2xx response that is not an
// envelope fails loudly instead of being silently accepted as an empty result.
func TestAPIClientRejectsNonEnvelopeSuccess(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		_, _ = fmt.Fprint(w, "not-json")
	}))
	defer server.Close()
	client := NewAPIClient(server.URL, "")
	_, err := client.ListEndpoints(context.Background())
	if err == nil {
		t.Fatal("non-envelope success response succeeded")
	}
	if !strings.Contains(err.Error(), "not a valid envelope") {
		t.Fatalf("error=%q does not name the envelope contract", err.Error())
	}
}
