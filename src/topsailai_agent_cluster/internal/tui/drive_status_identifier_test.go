package tui

import (
	"context"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// TestDriveStatusResolvesAProviderSessionID proves the identifier the help entry
// advertises is actually accepted.
//
// The help entry states "session/resource ID, provider session ID, or a bare list
// row number", and the interactive surface resolves all three. The standalone
// resolver compared only the cluster resource ID, so an operator who copied the
// provider session ID out of a provider record was told the session "was not
// reported by endpoint", which is false: the row was there under another name. The
// message sent the investigation to the inventory instead of to the identifier.
func TestDriveStatusResolvesAProviderSessionID(t *testing.T) {
	stub := driveStub()
	var out strings.Builder

	if err := (CommandRunner{API: stub, Policy: LegacyPolicy}).DriveStatus(context.Background(), &out, "endpoint-1", "provider-res-1", false); err != nil {
		t.Fatalf("a provider session ID the help entry advertises was refused: %v", err)
	}
	for _, want := range []string{"session: res-1", "drive_state: running", "drive_pid: 4242"} {
		if !strings.Contains(out.String(), want) {
			t.Fatalf("drive status missing %q: %q", want, out.String())
		}
	}
}

// TestDriveStatusPrefersTheResourceIDNamespace proves the routing identity wins a
// collision, so a provider session ID that happens to equal another row's resource
// ID cannot silently select the wrong row.
//
// The two namespaces are independent, so a collision is possible and must resolve
// deterministically. The resource ID is the routing identity, which is why it is
// searched first.
func TestDriveStatusPrefersTheResourceIDNamespace(t *testing.T) {
	stub := driveStub()
	report := stub.reports["endpoint-1"]
	// The first row's provider session ID equals the second row's resource ID.
	report.Sessions[0].ProviderSessionID = "res-1b"
	report.Sessions = append(report.Sessions, protocol.Session{
		ClusterSessionID:   "res-1b",
		ProviderSessionID:  "provider-1b",
		ProviderGeneration: "generation-1b",
		State:              "stopped",
		CollectionStatus:   protocol.CollectionSucceeded,
	})
	stub.reports["endpoint-1"] = report
	var out strings.Builder

	if err := (CommandRunner{API: stub, Policy: LegacyPolicy}).DriveStatus(context.Background(), &out, "endpoint-1", "res-1b", false); err != nil {
		t.Fatalf("DriveStatus: %v", err)
	}
	if !strings.Contains(out.String(), "session: res-1b") {
		t.Fatalf("the resource ID namespace did not win the collision: %q", out.String())
	}
}

// TestDriveStatusRejectsAnAmbiguousProviderSessionID proves several rows sharing one
// provider session ID are refused rather than resolved to the first.
//
// One provider session can own several output rows, so the identifier genuinely
// names more than one controller. Picking one would report a different row's state
// under the identifier the operator typed.
func TestDriveStatusRejectsAnAmbiguousProviderSessionID(t *testing.T) {
	stub := driveStub()
	report := stub.reports["endpoint-1"]
	report.Sessions = append(report.Sessions, protocol.Session{
		ClusterSessionID:   "res-1b",
		ProviderSessionID:  "provider-res-1",
		ProviderGeneration: "generation-1b",
		State:              "stopped",
		CollectionStatus:   protocol.CollectionSucceeded,
	})
	stub.reports["endpoint-1"] = report
	var out strings.Builder

	err := (CommandRunner{API: stub, Policy: LegacyPolicy}).DriveStatus(context.Background(), &out, "endpoint-1", "provider-res-1", false)

	if err == nil {
		t.Fatalf("an ambiguous provider session ID was resolved to one row instead of being refused")
	}
	if !strings.Contains(err.Error(), "matches 2 sessions") {
		t.Fatalf("the refusal does not state the ambiguity, so the operator cannot tell it from a miss: %v", err)
	}
	if out.Len() != 0 {
		t.Fatalf("an ambiguous identifier wrote output: %q", out.String())
	}
}

// TestDriveStatusStillRejectsAnUnknownIdentifier proves a genuine miss keeps its
// message, so the new namespace did not turn every miss into an ambiguity.
func TestDriveStatusStillRejectsAnUnknownIdentifier(t *testing.T) {
	var out strings.Builder

	err := (CommandRunner{API: driveStub(), Policy: LegacyPolicy}).DriveStatus(context.Background(), &out, "endpoint-1", "res-missing", false)

	if err == nil || err.Error() != `session "res-missing" was not reported by endpoint "endpoint-1"` {
		t.Fatalf("error=%v want the unreported message", err)
	}
}
