package packaging_test

import (
	"encoding/json"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"testing"
)

// extractPackagedBinary writes one executable from a package payload to disk and
// returns its path.
//
// The payload is read as bytes rather than through readPackagedFile, because that
// helper returns a string for text assertions. A binary survives a string round
// trip in Go, but writing the bytes directly keeps the extraction honest: the
// file that is executed is exactly the file the package ships, with no decoding
// step that could mask a difference.
func extractPackagedBinary(t *testing.T, pkg *debPackage, path string) string {
	t.Helper()
	fsys, err := exec.Command("dpkg-deb", "--fsys-tarfile", pkg.path).Output()
	if err != nil {
		t.Fatalf("cannot read the payload of %s: %v", pkg.path, err)
	}
	command := exec.Command("tar", "-xO", path)
	command.Stdin = strings.NewReader(string(fsys))
	payload, err := command.Output()
	if err != nil {
		t.Fatalf("cannot extract %s from %s: %v", path, pkg.path, err)
	}
	if len(payload) == 0 {
		t.Fatalf("%s is empty in %s", path, pkg.path)
	}
	// The extraction directory lives inside the shared build tree, so the
	// artifact stays under the project's .tmp folder and TestMain removes it
	// with the packages it came from.
	dir, err := os.MkdirTemp(debWorkDir, "bin-")
	if err != nil {
		t.Fatalf("cannot create an extraction directory: %v", err)
	}
	extracted := filepath.Join(dir, filepath.Base(path))
	if err := os.WriteFile(extracted, payload, 0o755); err != nil {
		t.Fatalf("cannot write %s: %v", extracted, err)
	}
	return extracted
}

// runPackagedBinary executes an extracted binary and returns its combined output
// and exit code.
//
// The environment is emptied on purpose. A version request must be answerable by
// the binary alone: if the answer depended on a configuration variable, an
// operator diagnosing a broken deployment would be the one who cannot get it.
func runPackagedBinary(t *testing.T, binary string, args ...string) (string, int) {
	t.Helper()
	command := exec.Command(binary, args...)
	command.Env = []string{"PATH=/usr/bin:/bin"}
	output, err := command.CombinedOutput()
	if err == nil {
		return string(output), 0
	}
	if exitErr, ok := err.(*exec.ExitError); ok {
		return string(output), exitErr.ExitCode()
	}
	t.Fatalf("cannot run %s: %v", binary, err)
	return "", -1
}

// TestDebBinariesReportThePackagedVersion proves the shipped binary carries the
// version the package was built with.
//
// Reading the build script would prove only that the script contains an injection
// flag. The binary is the artifact an operator actually runs, so the assertion
// executes it. The expected value is debTestVersion rather than a release number,
// because a hardcoded release would pass whether or not the injection reached the
// binary, and the default value is asserted absent for the same reason: a binary
// that still says "0.0.0-unpackaged" was built without the injection even though
// the package around it carries a version.
func TestDebBinariesReportThePackagedVersion(t *testing.T) {
	packages := buildDebPackages(t)

	cases := []struct {
		name      string
		pkg       string
		path      string
		component string
	}{
		{name: "server", pkg: "server", path: debOptDir + "/bin/agent-cluster-server", component: "agent-cluster-server"},
		{name: "endpoint", pkg: "endpoint", path: debOptDir + "/bin/agent-cluster-endpoint", component: "agent-cluster-endpoint"},
		{name: "cli", pkg: "endpoint", path: debOptDir + "/bin/agent-cluster-cli", component: "agent-cluster-cli"},
	}

	for _, tc := range cases {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			binary := extractPackagedBinary(t, packages[tc.pkg], tc.path)

			for _, flag := range []string{"-v", "--version"} {
				output, code := runPackagedBinary(t, binary, flag)
				if code != 0 {
					t.Fatalf("%s %s exited %d, want 0; output: %s", tc.component, flag, code, output)
				}
				if !strings.Contains(output, tc.component) {
					t.Fatalf("%s %s did not name the component %q; output: %s", tc.component, flag, tc.component, output)
				}
				if !strings.Contains(output, debTestVersion) {
					t.Fatalf("%s %s did not report the packaged version %q; output: %s", tc.component, flag, debTestVersion, output)
				}
				if strings.Contains(output, "0.0.0-unpackaged") {
					t.Fatalf("%s %s reported the unpackaged default, so the build did not inject the version; output: %s", tc.component, flag, output)
				}
			}
		})
	}
}

// TestDebBinariesAnswerVersionWithoutConfiguration proves the version request is
// answered before configuration is loaded.
//
// A daemon that loaded configuration first would refuse to state its own version
// on a node whose TLS material or token is missing, which is exactly the node an
// operator is trying to identify. The empty environment in runPackagedBinary is
// what makes this a real check: the binary has no configuration to load, so a
// version answer proves the request was handled earlier.
func TestDebBinariesAnswerVersionWithoutConfiguration(t *testing.T) {
	packages := buildDebPackages(t)

	for _, tc := range []struct {
		name string
		pkg  string
		path string
	}{
		{name: "server", pkg: "server", path: debOptDir + "/bin/agent-cluster-server"},
		{name: "endpoint", pkg: "endpoint", path: debOptDir + "/bin/agent-cluster-endpoint"},
	} {
		tc := tc
		t.Run(tc.name, func(t *testing.T) {
			binary := extractPackagedBinary(t, packages[tc.pkg], tc.path)
			output, code := runPackagedBinary(t, binary, "--version")
			if code != 0 {
				t.Fatalf("%s --version exited %d without configuration, want 0; output: %s", tc.name, code, output)
			}
			if strings.Contains(output, "required") || strings.Contains(output, "cannot") {
				t.Fatalf("%s --version reported a configuration failure instead of a version; output: %s", tc.name, output)
			}
		})
	}
}

// TestDebCLIVersionJSONIsMachineReadable proves the structured form is one JSON
// document a script can parse.
//
// The human-readable layout is asserted by the test above; this one exists because
// the two forms are separate code paths, and a script that receives a multi-line
// block instead of a document fails in a way that looks like a broken pipeline
// rather than a broken flag.
func TestDebCLIVersionJSONIsMachineReadable(t *testing.T) {
	packages := buildDebPackages(t)
	binary := extractPackagedBinary(t, packages["endpoint"], debOptDir+"/bin/agent-cluster-cli")

	output, code := runPackagedBinary(t, binary, "--json", "-v")
	if code != 0 {
		t.Fatalf("agent-cluster-cli --json -v exited %d, want 0; output: %s", code, output)
	}
	trimmed := strings.TrimSpace(output)
	if strings.Contains(trimmed, "\n") {
		t.Fatalf("the structured form must be one line; output: %s", output)
	}
	var document struct {
		Component string `json:"component"`
		Version   string `json:"version"`
		Commit    string `json:"commit"`
		Built     string `json:"built"`
	}
	if err := json.Unmarshal([]byte(trimmed), &document); err != nil {
		t.Fatalf("the structured form is not valid JSON: %v; output: %s", err, output)
	}
	if document.Component != "agent-cluster-cli" {
		t.Fatalf("component is %q, want agent-cluster-cli", document.Component)
	}
	if document.Version != debTestVersion {
		t.Fatalf("version is %q, want %q", document.Version, debTestVersion)
	}
	// The commit and the build time are the facts that distinguish two builds of
	// one release, so an empty value would make the document unable to answer the
	// question it exists for.
	if document.Commit == "" || document.Commit == "unknown" {
		t.Fatalf("commit is %q, so the build did not record its source revision", document.Commit)
	}
	if document.Built == "" || document.Built == "unknown" {
		t.Fatalf("built is %q, so the build did not record its build time", document.Built)
	}
}
