package providerconformance

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// repoFile reads one file from the repository root, so a guard can assert what
// the shipped build and packaging inputs actually say rather than restating it.
func repoFile(t *testing.T, parts ...string) string {
	t.Helper()
	path := filepath.Join(append([]string{"..", ".."}, parts...)...)
	data, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	return string(data)
}

// providerCaseBody returns the text of the `provider)` branch of the role case
// statement in make-deb.sh, so a guard can assert what that branch rejects
// without matching a token that appears elsewhere in the script.
func providerCaseBody(t *testing.T, script string) string {
	t.Helper()
	const marker = "    provider)\n"
	start := strings.Index(script, marker)
	if start < 0 {
		t.Fatalf("make-deb.sh has no provider branch, so the packaging role set changed")
	}
	rest := script[start:]
	end := strings.Index(rest, "\n    *) die \"--role must be")
	if end < 0 {
		t.Fatalf("make-deb.sh provider branch has no terminating case arm")
	}
	return rest[:end]
}

// TestMockProviderTypeIsRefusedByThePackager proves the Mock Provider cannot be
// turned into a Debian package. The script states that the Mock Provider is never
// packaged, but the module directory exists and the type validation accepts any
// lowercase token, so without an explicit refusal `make deb-provider
// DEB_PROVIDER_TYPE=mock` builds an installable package that carries a test
// artifact into a deployment.
func TestMockProviderTypeIsRefusedByThePackager(t *testing.T) {
	body := providerCaseBody(t, repoFile(t, "scripts", "make-deb.sh"))
	if !strings.Contains(body, `"${PROVIDER_TYPE}" != "mock"`) {
		t.Fatalf("make-deb.sh does not compare the provider type against mock, so the Mock Provider can be packaged")
	}
	if !strings.Contains(body, "is never packaged") {
		t.Fatalf("make-deb.sh refuses mock without saying why, so a later reader cannot tell the refusal is deliberate")
	}
}

// TestTopsailaiProviderTypeIsStillAccepted is the reverse baseline. A refusal that
// rejected every provider type would satisfy the guard above while breaking the
// only real Provider, so the accepted path is pinned too.
func TestTopsailaiProviderTypeIsStillAccepted(t *testing.T) {
	body := providerCaseBody(t, repoFile(t, "scripts", "make-deb.sh"))
	if strings.Contains(body, `"${PROVIDER_TYPE}" != "topsailai"`) {
		t.Fatalf("make-deb.sh refuses the topsailai Provider, so the only real Provider cannot be packaged")
	}
	if strings.Contains(body, "case \"${PROVIDER_TYPE}\" in\n            mock") {
		t.Fatalf("make-deb.sh rejects mock through a case arm that could grow to reject other types")
	}
}

// TestDefaultDebTargetDoesNotBuildProviders proves the aggregate `deb` target
// stays free of Provider packages. A Provider is optional by design, so building
// one as part of the default set would install a Provider on a node that never
// asked for it.
func TestDefaultDebTargetDoesNotBuildProviders(t *testing.T) {
	makefile := repoFile(t, "Makefile")
	start := strings.Index(makefile, "\ndeb:\n")
	if start < 0 {
		t.Fatalf("Makefile has no deb target")
	}
	rest := makefile[start+len("\ndeb:\n"):]
	end := strings.Index(rest, "\n# ")
	if end < 0 {
		end = len(rest)
	}
	body := rest[:end]
	if strings.Contains(body, "deb-provider") {
		t.Fatalf("the default deb target builds a Provider package, so a node receives a Provider it never asked for")
	}
	for _, role := range []string{"deb-node", "deb-server", "deb-endpoint"} {
		if !strings.Contains(body, role) {
			t.Fatalf("the default deb target no longer builds %s, so the guard is reading the wrong recipe", role)
		}
	}
}

// TestDockerImageCopiesNoProviderModule proves the runtime image carries no
// Provider module. The build stage copies the whole tree, which is harmless
// because only the server binary leaves it; a copy in the runtime stage would bake
// the Mock Provider into every deployment image.
func TestDockerImageCopiesNoProviderModule(t *testing.T) {
	dockerfile := repoFile(t, "docker", "Dockerfile")
	const runtimeMarker = "FROM alpine:"
	start := strings.Index(dockerfile, runtimeMarker)
	if start < 0 {
		t.Fatalf("docker/Dockerfile has no runtime stage, so the guard cannot tell the stages apart")
	}
	runtime := dockerfile[start:]
	for _, forbidden := range []string{"COPY . .", "COPY providers"} {
		if strings.Contains(runtime, forbidden) {
			t.Fatalf("the runtime stage contains %q, so the image carries source or a Provider module", forbidden)
		}
	}
	if !strings.Contains(runtime, "COPY --from=build /out/agent-cluster-server") {
		t.Fatalf("the runtime stage no longer copies the server binary, so the guard is reading the wrong stage")
	}
}
