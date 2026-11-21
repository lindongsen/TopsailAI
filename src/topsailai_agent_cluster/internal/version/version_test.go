package version

import (
	"bytes"
	"encoding/json"
	"strings"
	"testing"
)

// TestRequestedRecognisesBothSpellings proves the two spellings are one request.
//
// An operator who learned -v from another tool and one who writes --version must
// receive the same answer, because a spelling that silently does nothing reads as
// "this binary has no version" rather than "you typed the other one".
func TestRequestedRecognisesBothSpellings(t *testing.T) {
	for _, args := range [][]string{
		{"-v"},
		{"--version"},
		{"list", "-v"},
		{"--json", "-v"},
		{"-v", "--json"},
	} {
		if !Requested(args, nil) {
			t.Fatalf("Requested(%q) = false, want true", args)
		}
	}
}

// TestRequestedIgnoresDataAfterTerminator proves a literal -v stays data.
//
// After "--" every token belongs to the command, so "exec ... -- ls -v" must pass
// -v to ls. Answering it here would make a version flag steal an argument from a
// command that was explicitly told where its data begins.
func TestRequestedIgnoresDataAfterTerminator(t *testing.T) {
	if Requested([]string{"exec", "ep", "res", "gen", "--", "ls", "-v"}, nil) {
		t.Fatal("Requested answered a -v written after the -- terminator")
	}
}

// TestRequestedSkipsAValueThatLooksLikeTheFlag proves a value is not a request.
//
// A value-taking option owns the following argument, so "--endpoint -v" names an
// endpoint called "-v" rather than asking for the version. Without this the
// version flag would be unreachable for any command that takes a value, because
// the value would be consumed as the request instead.
func TestRequestedSkipsAValueThatLooksLikeTheFlag(t *testing.T) {
	valueOptions := map[string]bool{"endpoint": true}
	if Requested([]string{"--endpoint", "-v", "list"}, valueOptions) {
		t.Fatal("Requested read an option value as the version request")
	}
	if !Requested([]string{"--endpoint", "ep", "-v"}, valueOptions) {
		t.Fatal("Requested missed a -v written after an option and its value")
	}
}

// TestWriteRendersEveryFact proves the human-readable form carries the facts that
// distinguish two builds of one release.
//
// A version number alone cannot tell a rebuilt binary from the shipped one, so the
// commit and the build time are the load-bearing fields. The assertion names them
// rather than checking that the output is non-empty, because an empty renderer
// would satisfy a non-empty check.
func TestWriteRendersEveryFact(t *testing.T) {
	previous := snapshot()
	defer restore(previous)
	Version, Commit, BuildTime = "1.3.0", "2cd6b9e1f5f3504296abd29af9e40c75ab0a371a", "2026-11-21T05:16:12Z"

	var out bytes.Buffer
	if err := Write(&out, "agent-cluster-cli"); err != nil {
		t.Fatalf("Write returned %v", err)
	}
	rendered := out.String()
	for _, want := range []string{
		"agent-cluster-cli 1.3.0",
		"commit:  2cd6b9e1f5f3504296abd29af9e40c75ab0a371a",
		"built:   2026-11-21T05:16:12Z",
	} {
		if !strings.Contains(rendered, want) {
			t.Fatalf("rendered output does not contain %q:\n%s", want, rendered)
		}
	}
}

// TestWriteJSONIsOneParseableDocument proves the structured form is machine
// readable, because a script that has to parse the human layout is the reason
// this form exists.
func TestWriteJSONIsOneParseableDocument(t *testing.T) {
	previous := snapshot()
	defer restore(previous)
	Version, Commit, BuildTime = "1.3.0", "abc123", "2026-11-21T05:16:12Z"

	var out bytes.Buffer
	if err := WriteJSON(&out, "agent-cluster-endpoint"); err != nil {
		t.Fatalf("WriteJSON returned %v", err)
	}
	var decoded Identity
	if err := json.Unmarshal(out.Bytes(), &decoded); err != nil {
		t.Fatalf("the structured form is not one JSON document: %v\n%s", err, out.String())
	}
	if decoded.Component != "agent-cluster-endpoint" || decoded.Version != "1.3.0" || decoded.Commit != "abc123" {
		t.Fatalf("decoded identity = %+v, want the injected values", decoded)
	}
	if decoded.Go == "" || decoded.OS == "" || decoded.Arch == "" {
		t.Fatalf("decoded identity omits the runtime facts: %+v", decoded)
	}
}

// TestUninjectedBuildDoesNotClaimARelease proves the default is honest.
//
// A binary that was never packaged must not report a version-shaped value,
// because an operator who reads "1.3.0" from a local build would believe they are
// running the shipped release. This is the assertion that keeps the default from
// drifting into something plausible.
func TestUninjectedBuildDoesNotClaimARelease(t *testing.T) {
	previous := snapshot()
	defer restore(previous)
	Version, Commit, BuildTime = "0.0.0-unpackaged", "unknown", "unknown"

	var out bytes.Buffer
	if err := Write(&out, "agent-cluster-server"); err != nil {
		t.Fatalf("Write returned %v", err)
	}
	if !strings.Contains(out.String(), "0.0.0-unpackaged") {
		t.Fatalf("an uninjected build does not report its honest default:\n%s", out.String())
	}
}

// snapshot captures the injected values so a test can restore them.
func snapshot() [3]string {
	return [3]string{Version, Commit, BuildTime}
}

// restore puts the injected values back, so one test cannot change what another
// observes.
func restore(values [3]string) {
	Version, Commit, BuildTime = values[0], values[1], values[2]
}
