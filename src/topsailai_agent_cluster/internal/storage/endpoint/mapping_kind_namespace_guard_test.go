package endpointstorage

import (
	"context"
	"os"
	"regexp"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/protocol"
)

// resourceKindValues maps every identifier named in the IsResourceKind switch to
// the value it stands for. The guard compares this map against the switch text, so
// a kind added to the vocabulary without a value here fails the guard instead of
// silently escaping the namespace check.
var resourceKindValues = map[string]string{
	"ResourceAgent":         protocol.ResourceAgent,
	"ResourceSession":       protocol.ResourceSession,
	"ResourceTask":          protocol.ResourceTask,
	"ResourceLaunchProfile": protocol.ResourceLaunchProfile,
	"ResourceModelProfile":  protocol.ResourceModelProfile,
	"ResourceProject":       protocol.ResourceProject,
}

// declaredResourceKinds reads the IsResourceKind switch and returns the constant
// identifiers it accepts. The guard derives the vocabulary from the source that
// enforces it rather than restating a list, so the two cannot drift apart.
func declaredResourceKinds(t *testing.T) []string {
	t.Helper()
	source, err := os.ReadFile("../../protocol/resource_kind.go")
	if err != nil {
		t.Fatalf("read the resource kind vocabulary: %v", err)
	}
	pattern := regexp.MustCompile(`case\s+([A-Za-z0-9_,\s]+):`)
	match := pattern.FindStringSubmatch(string(source))
	if match == nil {
		t.Fatal("IsResourceKind no longer declares a case list, so this guard checked nothing")
	}
	identifiers := []string{}
	for _, identifier := range strings.Split(match[1], ",") {
		identifiers = append(identifiers, strings.TrimSpace(identifier))
	}
	if len(identifiers) == 0 {
		t.Fatal("IsResourceKind declares an empty case list, so this guard checked nothing")
	}
	return identifiers
}

// TestResourceKindVocabularyIsClosed proves the guard covers every kind the
// validator accepts. A kind added to IsResourceKind without a value in this guard
// would otherwise be stored under a namespace nothing tests.
func TestResourceKindVocabularyIsClosed(t *testing.T) {
	declared := declaredResourceKinds(t)
	for _, identifier := range declared {
		if _, known := resourceKindValues[identifier]; !known {
			t.Fatalf("IsResourceKind accepts %s but this guard has no value for it, so its namespace is untested", identifier)
		}
	}
	if len(declared) != len(resourceKindValues) {
		t.Fatalf("IsResourceKind declares %d kinds but this guard names %d", len(declared), len(resourceKindValues))
	}
}

// TestEveryResourceKindGetsItsOwnNamespace proves the kind dimension separates
// every kind in the vocabulary, not only the Session and Task pair. One provider
// key is reused across all kinds, so a kind that shares a namespace with another
// collapses two distinct resources onto one Cluster ID.
func TestEveryResourceKindGetsItsOwnNamespace(t *testing.T) {
	store, ctx := openTestStore(t)
	const sharedKey = "shared-provider-key"
	seen := map[string]string{}
	for identifier, kind := range resourceKindValues {
		if !protocol.IsResourceKind(kind) {
			t.Fatalf("%s=%q is not accepted by IsResourceKind", identifier, kind)
		}
		mapping, err := store.GetOrCreateResourceID(ctx, "adapter-a", kind, sharedKey, 100)
		if err != nil {
			t.Fatalf("%s=%q is in the vocabulary but cannot be stored: %v", identifier, kind, err)
		}
		if previous, exists := seen[mapping.ResourceID]; exists {
			t.Fatalf("%s and %s shared Cluster ID %q for one provider key", identifier, previous, mapping.ResourceID)
		}
		seen[mapping.ResourceID] = identifier
	}
	if len(seen) != len(resourceKindValues) {
		t.Fatalf("stored %d Cluster IDs for %d kinds", len(seen), len(resourceKindValues))
	}
}

// TestResourceKindNamespaceIsOrderIndependent proves the separation does not
// depend on which kind is created first. The existing Session-then-Task test only
// covers one order, so a first-writer-wins defect would pass it.
func TestResourceKindNamespaceIsOrderIndependent(t *testing.T) {
	store, ctx := openTestStore(t)
	task, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceTask, "shared-key", 100)
	if err != nil {
		t.Fatal(err)
	}
	session, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceSession, "shared-key", 101)
	if err != nil {
		t.Fatal(err)
	}
	if task.ResourceID == session.ResourceID {
		t.Fatalf("task created first still shared Cluster ID %q with the session", task.ResourceID)
	}
	if task.ResourceKind != protocol.ResourceTask || session.ResourceKind != protocol.ResourceSession {
		t.Fatalf("resource kinds task=%q session=%q", task.ResourceKind, session.ResourceKind)
	}
}

// TestResourceKindNamespaceSurvivesRestart proves the separation is durable rather
// than an artefact of one in-memory session. A reopened store must still resolve
// each kind to its own Cluster ID.
func TestResourceKindNamespaceSurvivesRestart(t *testing.T) {
	ctx := context.Background()
	path := t.TempDir() + "/endpoint.db"
	store, err := Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	session, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceSession, "shared-key", 100)
	if err != nil {
		t.Fatal(err)
	}
	task, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceTask, "shared-key", 101)
	if err != nil {
		t.Fatal(err)
	}
	if err := store.Close(); err != nil {
		t.Fatal(err)
	}
	store, err = Open(ctx, path)
	if err != nil {
		t.Fatal(err)
	}
	defer store.Close()
	reopenedSession, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceSession, "shared-key", 200)
	if err != nil {
		t.Fatal(err)
	}
	reopenedTask, err := store.GetOrCreateResourceID(ctx, "adapter-a", protocol.ResourceTask, "shared-key", 201)
	if err != nil {
		t.Fatal(err)
	}
	if reopenedSession.ResourceID != session.ResourceID {
		t.Fatalf("session resource ID changed to %q", reopenedSession.ResourceID)
	}
	if reopenedTask.ResourceID != task.ResourceID {
		t.Fatalf("task resource ID changed to %q", reopenedTask.ResourceID)
	}
	if reopenedSession.ResourceID == reopenedTask.ResourceID {
		t.Fatalf("reopened store collapsed both kinds onto %q", reopenedSession.ResourceID)
	}
}
