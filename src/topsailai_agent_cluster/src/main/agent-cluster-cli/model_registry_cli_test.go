package main

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"sync"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/tui"
)

// modelSurfaceRecorder serves the endpoints list and records every model path the
// standalone surface requests.
//
// The endpoints list is served because every model command resolves its endpoint
// first, so an unreachable Server would fail before the interesting request. The
// recorded paths are the evidence: the registry read and the session catalog read have
// the same arity, so only the requested path distinguishes them.
type modelSurfaceRecorder struct {
	mu    sync.Mutex
	paths []string
}

func (r *modelSurfaceRecorder) record(path string) {
	r.mu.Lock()
	defer r.mu.Unlock()
	r.paths = append(r.paths, path)
}

// requested reports whether any recorded path contains the given fragment.
func (r *modelSurfaceRecorder) requested(fragment string) bool {
	r.mu.Lock()
	defer r.mu.Unlock()
	for _, path := range r.paths {
		if strings.Contains(path, fragment) {
			return true
		}
	}
	return false
}

// modelSurfaceServer serves one online endpoint and answers every model read with an
// empty successful document, so a command reaches its model request instead of failing
// on the endpoint lookup.
func modelSurfaceServer(t *testing.T) (*httptest.Server, *modelSurfaceRecorder) {
	t.Helper()
	recorder := &modelSurfaceRecorder{}
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		recorder.record(r.URL.Path)
		if r.Header.Get("Authorization") != "Bearer test-token" {
			writeListTestEnvelope(w, http.StatusUnauthorized, "unauthorized", nil)
			return
		}
		switch {
		case r.URL.Path == "/api/v1/endpoints":
			writeListTestEnvelope(w, http.StatusOK, "success", []protocol.Endpoint{
				{EndpointID: "endpoint-1", DisplayName: "endpoint-1", ConnectionState: "online"},
			})
		case r.URL.Path == "/api/v1/model-registry":
			writeListTestEnvelope(w, http.StatusOK, "success", protocol.ModelRegistry{
				Entries: []protocol.ModelRegistryEntry{{
					ModelProfileID:      "mp_alpha",
					ProviderDisplayName: "alpha",
					Available:           true,
				}},
				CurrentProfileID: "mp_alpha",
				CurrentSource:    protocol.ModelSourceWorkspace,
			})
		case r.URL.Path == "/api/v1/model-catalog":
			writeListTestEnvelope(w, http.StatusOK, "success", protocol.ModelCatalog{
				Profiles: []protocol.ModelProfile{{
					ModelProfileID:      "mp_alpha",
					ProviderDisplayName: "alpha",
					Available:           true,
				}},
			})
		default:
			writeListTestEnvelope(w, http.StatusNotFound, "not found", nil)
		}
	}))
	t.Cleanup(server.Close)
	return server, recorder
}

// runModelSurface executes one standalone invocation against the fixture server.
func runModelSurface(t *testing.T, server *httptest.Server, args ...string) (string, error) {
	t.Helper()
	var output, diagnostics strings.Builder
	full := append([]string{"--server-url", server.URL, "--token", "test-token", "--auth-mode", "bearer"}, args...)
	err := runWithIO(full, strings.NewReader(""), &output, &diagnostics, false, nil)
	return output.String(), err
}

// TestModelRegistryReadsTheRegistryNotTheCatalog proves "model registry" reaches the
// machine-scoped registry read instead of falling through to the session catalog.
//
// The two forms have the same arity, so a dispatcher that lost the registry branch
// would still accept the invocation and still issue a request. Only the requested path
// distinguishes them, which is why this test asserts the path rather than the exit
// status: a fall-through produces no usage error and no unknown-command error.
func TestModelRegistryReadsTheRegistryNotTheCatalog(t *testing.T) {
	server, recorder := modelSurfaceServer(t)
	if _, err := runModelSurface(t, server, "model", "registry", "endpoint-1"); err != nil {
		t.Fatalf("model registry failed: %v", err)
	}
	if !recorder.requested("/api/v1/model-registry") {
		t.Fatalf("model registry did not read the registry; requested paths: %v", recorder.paths)
	}
	if recorder.requested("/api/v1/model-catalog") {
		t.Fatalf("model registry fell through to the session catalog; requested paths: %v", recorder.paths)
	}
}

// TestModelRegistryRendersTheMachineRegistry proves the registry read renders the
// machine-scoped table, including the marker for the model a launch would use.
//
// A read that reached the right path but rendered the session catalog would still be
// wrong, so the rendered bytes are asserted as well as the requested path.
func TestModelRegistryRendersTheMachineRegistry(t *testing.T) {
	server, _ := modelSurfaceServer(t)
	output, err := runModelSurface(t, server, "model", "registry", "endpoint-1")
	if err != nil {
		t.Fatalf("model registry failed: %v", err)
	}
	if !strings.Contains(output, "MODEL") {
		t.Fatalf("model registry did not render a model table:\n%s", output)
	}
	if !strings.Contains(output, "* alpha") {
		t.Fatalf("model registry did not mark the model in use:\n%s", output)
	}
	if !strings.Contains(output, "launches from this endpoint use the model marked *") {
		t.Fatalf("model registry did not state where the selection came from:\n%s", output)
	}
}

// TestModelRegistryJSONCarriesTheOpaqueIdentifier proves --json keeps the selector a
// script needs.
//
// The rendered table hides the identifier column because the value is long and opaque,
// so a script that only had the table could not address a model. The JSON document is
// the surface that keeps it.
func TestModelRegistryJSONCarriesTheOpaqueIdentifier(t *testing.T) {
	server, _ := modelSurfaceServer(t)
	output, err := runModelSurface(t, server, "--json", "model", "registry", "endpoint-1")
	if err != nil {
		t.Fatalf("model registry --json failed: %v", err)
	}
	if !strings.Contains(output, "mp_alpha") {
		t.Fatalf("model registry --json dropped the opaque identifier:\n%s", output)
	}
}

// TestModelSetReadsTheRegistryBeforeSubmitting proves "model set" resolves its
// selector against the machine-scoped registry read.
//
// The selector is resolved against a live read so an unknown or unavailable model is
// refused before anything is submitted. That resolution is the first model request, so
// the requested path proves the command reached the registry rather than the catalog.
func TestModelSetReadsTheRegistryBeforeSubmitting(t *testing.T) {
	server, recorder := modelSurfaceServer(t)
	// The submission itself is expected to fail, because the fixture advertises no
	// capabilities. What matters is that the registry was read first.
	_, _ = runModelSurface(t, server, "--yes", "model", "set", "endpoint-1", "mp_alpha")
	if !recorder.requested("/api/v1/model-registry") {
		t.Fatalf("model set did not resolve against the registry; requested paths: %v", recorder.paths)
	}
	if recorder.requested("/api/v1/model-catalog") {
		t.Fatalf("model set fell through to the session catalog; requested paths: %v", recorder.paths)
	}
}

// TestModelSetRefusesAnUnknownModelBeforeSubmitting proves an unknown selector is
// refused locally instead of being sent to the provider as an opaque value.
//
// The refusal must happen before any command is admitted, so the fixture records no
// command submission. Sending an unknown identifier would make the provider answer for
// a value the operator never saw in a registry.
func TestModelSetRefusesAnUnknownModelBeforeSubmitting(t *testing.T) {
	server, recorder := modelSurfaceServer(t)
	_, err := runModelSurface(t, server, "--yes", "model", "set", "endpoint-1", "mp_missing")
	if err == nil {
		t.Fatal("model set accepted a model that is not in the registry")
	}
	if !strings.Contains(err.Error(), "not in the current registry") {
		t.Fatalf("model set refused an unknown model with an unrelated message: %v", err)
	}
	if recorder.requested("/api/v1/commands") {
		t.Fatalf("model set submitted a command for an unknown model; requested paths: %v", recorder.paths)
	}
}

// TestModelSetRejectsRowNumber proves the standalone surface refuses a row number
// instead of resolving it against a table that was never rendered.
//
// A row number is a position in a table the operator saw. Accepting one here would let
// a script declare a model by counting rows of a table it never printed, and the count
// would silently mean a different model after any registry change. The refusal must
// happen before any request, so no path may be recorded.
func TestModelSetRejectsRowNumber(t *testing.T) {
	server, recorder := modelSurfaceServer(t)
	_, err := runModelSurface(t, server, "--yes", "model", "set", "endpoint-1", "1")
	if err == nil {
		t.Fatal("model set accepted a row number")
	}
	if !strings.Contains(err.Error(), "row number") {
		t.Fatalf("model set rejected a row number with an unrelated message: %v", err)
	}
	if len(recorder.paths) != 0 {
		t.Fatalf("model set issued a request before refusing a row number: %v", recorder.paths)
	}
}

// TestModelSetRequiresConfirmation proves the launch-default declaration is treated as
// mutating, exactly as the interactive surface treats it.
//
// A machine-wide declaration changes what every future launch on that machine uses, so
// it must not be applied by a script that forgot --yes. The refusal must name the
// confirmation rather than a transport failure.
func TestModelSetRequiresConfirmation(t *testing.T) {
	server, recorder := modelSurfaceServer(t)
	_, err := runModelSurface(t, server, "model", "set", "endpoint-1", "mp_alpha")
	if err == nil {
		t.Fatal("model set applied a machine-wide declaration without --yes")
	}
	if !strings.Contains(err.Error(), "confirmation required") {
		t.Fatalf("model set refused without --yes with an unrelated message: %v", err)
	}
	if recorder.requested("/api/v1/commands") {
		t.Fatalf("model set submitted a command without --yes; requested paths: %v", recorder.paths)
	}
}

// TestModelRegistryAndSetAreAdvertised proves the help surface states the forms the
// dispatcher accepts.
//
// The dispatcher and the help are two separate sources of truth: one decides what
// runs, the other decides what an operator believes runs. A form accepted but not
// advertised is undiscoverable, and a form advertised but not accepted is a promise
// the binary cannot keep.
func TestModelRegistryAndSetAreAdvertised(t *testing.T) {
	var output strings.Builder
	if err := tui.PrintNonInteractiveCommandHelp(&output, "model"); err != nil {
		t.Fatal(err)
	}
	help := output.String()
	for _, want := range []string{"model registry <endpoint-id-or-hostname>", "model set <endpoint-id-or-hostname>"} {
		if !strings.Contains(help, want) {
			t.Fatalf("standalone model help does not advertise %q:\n%s", want, help)
		}
	}
}

// TestModelSessionCatalogFormStillWorks proves the pre-existing session-scoped form
// was not displaced by the two new subcommands.
//
// The read form stays the default so an existing invocation keeps working. A
// dispatcher that treated every second argument as a subcommand would break it, and the
// breakage would appear only for an endpoint whose identifier is not "registry" or
// "set", which is why this case is asserted separately.
func TestModelSessionCatalogFormStillWorks(t *testing.T) {
	server, recorder := modelSurfaceServer(t)
	if _, err := runModelSurface(t, server, "model", "endpoint-1", "res_abc"); err != nil {
		t.Fatalf("the session catalog form failed: %v", err)
	}
	if !recorder.requested("/api/v1/model-catalog") {
		t.Fatalf("the session catalog form did not read the catalog; requested paths: %v", recorder.paths)
	}
	if recorder.requested("/api/v1/model-registry") {
		t.Fatalf("the session catalog form read the registry instead; requested paths: %v", recorder.paths)
	}
}
