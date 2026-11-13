package endpoint

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"os"
	"path/filepath"
	"strings"
	"sync"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

// replaceTestAdapter is one minted adapter instance. It records its own Close
// count so a test can prove a rejected candidate is closed and a serving version
// is not.
type replaceTestAdapter struct {
	command     string
	descriptor  adapter.Descriptor
	discoverErr error
	mu          sync.Mutex
	closes      int
	discovers   int
}

func (a *replaceTestAdapter) Describe(context.Context) (adapter.Descriptor, error) {
	return a.descriptor, nil
}

func (a *replaceTestAdapter) Discover(context.Context, adapter.DiscoverRequest) (adapter.DiscoverResult, error) {
	a.mu.Lock()
	a.discovers++
	a.mu.Unlock()
	if a.discoverErr != nil {
		return adapter.DiscoverResult{}, a.discoverErr
	}
	return adapter.DiscoverResult{Complete: true, CollectionStatus: protocol.CollectionSucceeded}, nil
}

func (a *replaceTestAdapter) Inspect(context.Context, adapter.InspectRequest) (adapter.InspectResult, error) {
	return adapter.InspectResult{}, adapter.ErrUnsupported
}

func (a *replaceTestAdapter) Execute(context.Context, adapter.ExecuteRequest) (adapter.ExecuteResult, error) {
	return adapter.ExecuteResult{}, adapter.ErrUnsupported
}

func (a *replaceTestAdapter) ReadOutput(context.Context, adapter.OutputRequest) (adapter.OutputResult, error) {
	return adapter.OutputResult{}, adapter.ErrUnsupported
}

func (a *replaceTestAdapter) QueryCommand(context.Context, adapter.CommandQuery) (adapter.CommandResult, error) {
	return adapter.CommandResult{}, adapter.ErrUnsupported
}

func (a *replaceTestAdapter) Watch(context.Context) (<-chan adapter.Event, error) {
	return nil, adapter.ErrUnsupported
}

func (a *replaceTestAdapter) Close() error {
	a.mu.Lock()
	defer a.mu.Unlock()
	a.closes++
	return nil
}

func (a *replaceTestAdapter) closeCount() int {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.closes
}

func (a *replaceTestAdapter) discoverCount() int {
	a.mu.Lock()
	defer a.mu.Unlock()
	return a.discovers
}

// replaceTestPublisher records the provider types it was asked to republish and
// can be told to fail, so a test can prove publication failure reverts the swap.
type replaceTestPublisher struct {
	err      error
	mu       sync.Mutex
	requests []string
}

func (p *replaceTestPublisher) RefreshDescriptors(_ context.Context, providerType string) error {
	p.mu.Lock()
	p.requests = append(p.requests, providerType)
	p.mu.Unlock()
	return p.err
}

func (p *replaceTestPublisher) published() []string {
	p.mu.Lock()
	defer p.mu.Unlock()
	return append([]string(nil), p.requests...)
}

// replaceTestFixture builds a registry whose factory mints one distinct adapter
// per call, deriving its descriptor from the configured command so a test can
// tell the previous version from the candidate.
//
// The factory also owns the two failure modes activation must survive: a command
// containing "bad-bootstrap" fails construction, which is how an incompatible
// Provider CLI is modelled, and Settings["discover_error"] makes the minted
// instance fail discovery, which is how a candidate that describes itself but
// cannot work is modelled.
type replaceTestFixture struct {
	registry  *adapter.Registry
	mu        sync.Mutex
	instances []*replaceTestAdapter
}

func newReplaceTestFixture(t *testing.T) *replaceTestFixture {
	t.Helper()
	fixture := &replaceTestFixture{registry: adapter.NewRegistry()}
	if err := fixture.registry.RegisterType("fixture", func(_ context.Context, config adapter.Config) (adapter.Adapter, error) {
		if strings.Contains(config.Command, "bad-bootstrap") {
			return nil, errors.New("protocol major version 9 is incompatible")
		}
		base := filepath.Base(config.Command)
		minted := &replaceTestAdapter{
			command: config.Command,
			descriptor: adapter.Descriptor{
				AdapterID:    config.AdapterID,
				ProviderType: config.ProviderType,
				DisplayName:  base,
				Version:      base,
				Capabilities: protocol.CapabilityDescriptor{Revision: "rev-" + base},
			},
		}
		if config.Settings["discover_error"] != "" {
			minted.discoverErr = errors.New("provider discovery failed")
		}
		fixture.mu.Lock()
		fixture.instances = append(fixture.instances, minted)
		fixture.mu.Unlock()
		return minted, nil
	}); err != nil {
		t.Fatalf("register type: %v", err)
	}
	return fixture
}

// configure creates one adapter from a command path and returns the instance.
func (f *replaceTestFixture) configure(t *testing.T, adapterID, command string, settings map[string]string) *replaceTestAdapter {
	t.Helper()
	before := f.count()
	if _, err := f.registry.Configure(context.Background(), adapter.Config{
		AdapterID:    adapterID,
		ProviderType: "fixture",
		Command:      command,
		Settings:     settings,
	}); err != nil {
		t.Fatalf("configure %s: %v", adapterID, err)
	}
	if f.count() != before+1 {
		t.Fatalf("factory did not mint one instance for %s", adapterID)
	}
	return f.last()
}

func (f *replaceTestFixture) count() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return len(f.instances)
}

func (f *replaceTestFixture) last() *replaceTestAdapter {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.instances[len(f.instances)-1]
}

// candidateFile writes one executable file and returns its absolute path.
func candidateFile(t *testing.T, name string, mode os.FileMode, content string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), name)
	if err := os.WriteFile(path, []byte(content), mode); err != nil {
		t.Fatalf("write candidate: %v", err)
	}
	return path
}

// TestValidateCandidateFileRejectsUnsafeArtifacts proves every artifact check
// rejects before the program is ever executed.
func TestValidateCandidateFileRejectsUnsafeArtifacts(t *testing.T) {
	executable := candidateFile(t, "provider", 0o755, "#!/bin/sh\nexit 0\n")
	notExecutable := candidateFile(t, "plain", 0o644, "data")
	empty := candidateFile(t, "empty", 0o755, "")
	directory := t.TempDir()
	symlinkPath := filepath.Join(t.TempDir(), "link")
	if err := os.Symlink(executable, symlinkPath); err != nil {
		t.Fatalf("create symlink: %v", err)
	}
	digest := sha256.Sum256([]byte("#!/bin/sh\nexit 0\n"))
	correctDigest := hex.EncodeToString(digest[:])

	cases := []struct {
		name    string
		request ReplaceRequest
		want    string
	}{
		{name: "empty path", request: ReplaceRequest{}, want: "path is required"},
		{name: "relative path", request: ReplaceRequest{Executable: "provider"}, want: "must be absolute"},
		{name: "missing file", request: ReplaceRequest{Executable: filepath.Join(t.TempDir(), "absent")}, want: "inspect candidate"},
		{name: "symlink", request: ReplaceRequest{Executable: symlinkPath}, want: "is a symlink"},
		{name: "directory", request: ReplaceRequest{Executable: directory}, want: "not a regular file"},
		{name: "not executable", request: ReplaceRequest{Executable: notExecutable}, want: "is not executable"},
		{name: "empty file", request: ReplaceRequest{Executable: empty}, want: "is empty"},
		{name: "oversized", request: ReplaceRequest{Executable: executable, MaxBytes: 1}, want: "above the 1 byte bound"},
		{name: "digest mismatch", request: ReplaceRequest{Executable: executable, ExpectedSHA256: strings.Repeat("0", 64)}, want: "does not match the expected"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			err := validateCandidateFile(testCase.request)
			if err == nil {
				t.Fatalf("unsafe candidate accepted: %#v", testCase.request)
			}
			if !strings.Contains(err.Error(), testCase.want) {
				t.Fatalf("error %q does not mention %q", err.Error(), testCase.want)
			}
		})
	}
	if err := validateCandidateFile(ReplaceRequest{Executable: executable, ExpectedSHA256: correctDigest}); err != nil {
		t.Fatalf("valid candidate rejected: %v", err)
	}
}

// TestReplaceRejectsUnknownAdapter proves activation cannot invent an adapter.
func TestReplaceRejectsUnknownAdapter(t *testing.T) {
	fixture := newReplaceTestFixture(t)
	replacer := &Replacer{Registry: fixture.registry, Publisher: &replaceTestPublisher{}}
	_, err := replacer.Replace(context.Background(), ReplaceRequest{AdapterID: "absent", Executable: candidateFile(t, "p", 0o755, "x")})
	if err == nil || !strings.Contains(err.Error(), "is not configured") {
		t.Fatalf("unknown adapter accepted: %v", err)
	}
}

// TestReplaceKeepsPreviousVersionWhenBootstrapFails proves an incompatible
// candidate never reaches the registry: the previous version keeps serving and
// the candidate is closed.
func TestReplaceKeepsPreviousVersionWhenBootstrapFails(t *testing.T) {
	fixture := newReplaceTestFixture(t)
	previous := fixture.configure(t, "a", "/opt/prev", nil)
	publisher := &replaceTestPublisher{}
	replacer := &Replacer{Registry: fixture.registry, Publisher: publisher}

	_, err := replacer.Replace(context.Background(), ReplaceRequest{AdapterID: "a", Executable: candidateFile(t, "bad-bootstrap", 0o755, "x")})
	if err == nil || !strings.Contains(err.Error(), "bootstrap candidate") {
		t.Fatalf("incompatible candidate accepted: %v", err)
	}
	serving, ok := fixture.registry.Get("a")
	if !ok || serving != previous {
		t.Fatal("previous version is no longer serving after a bootstrap failure")
	}
	if previous.closeCount() != 0 {
		t.Fatalf("previous version was closed: closes=%d", previous.closeCount())
	}
	if len(publisher.published()) != 0 {
		t.Fatalf("capabilities were republished for a rejected candidate: %v", publisher.published())
	}
}

// TestReplaceKeepsPreviousVersionWhenSmokeFails proves a candidate that
// describes itself but cannot discover is rejected and closed.
func TestReplaceKeepsPreviousVersionWhenSmokeFails(t *testing.T) {
	fixture := newReplaceTestFixture(t)
	previous := fixture.configure(t, "a", "/opt/prev", map[string]string{"discover_error": "1"})
	publisher := &replaceTestPublisher{}
	replacer := &Replacer{Registry: fixture.registry, Publisher: publisher}

	_, err := replacer.Replace(context.Background(), ReplaceRequest{AdapterID: "a", Executable: candidateFile(t, "next", 0o755, "x")})
	if err == nil || !strings.Contains(err.Error(), "smoke discovery failed") {
		t.Fatalf("candidate that cannot discover was accepted: %v", err)
	}
	serving, ok := fixture.registry.Get("a")
	if !ok || serving != previous {
		t.Fatal("previous version is no longer serving after a smoke failure")
	}
	candidate := fixture.last()
	if candidate.closeCount() != 1 {
		t.Fatalf("rejected candidate was not closed exactly once: closes=%d", candidate.closeCount())
	}
	if len(publisher.published()) != 0 {
		t.Fatalf("capabilities were republished for a rejected candidate: %v", publisher.published())
	}
}

// TestReplaceRejectsCandidateWithoutCapabilityRevision proves a candidate that
// cannot state its effective revision is not activatable, because the fleet could
// not be told what changed.
func TestReplaceRejectsCandidateWithoutCapabilityRevision(t *testing.T) {
	registry := adapter.NewRegistry()
	if err := registry.RegisterType("fixture", func(_ context.Context, config adapter.Config) (adapter.Adapter, error) {
		return &replaceTestAdapter{
			command:    config.Command,
			descriptor: adapter.Descriptor{ProviderType: config.ProviderType, Version: "v2"},
		}, nil
	}); err != nil {
		t.Fatalf("register type: %v", err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "a", ProviderType: "fixture", Command: "/opt/prev"}); err != nil {
		t.Fatalf("configure: %v", err)
	}
	replacer := &Replacer{Registry: registry, Publisher: &replaceTestPublisher{}}
	_, err := replacer.Replace(context.Background(), ReplaceRequest{AdapterID: "a", Executable: candidateFile(t, "next", 0o755, "x")})
	if err == nil || !strings.Contains(err.Error(), "no capability revision") {
		t.Fatalf("candidate without a revision was accepted: %v", err)
	}
}

// TestReplaceActivatesAndPublishesEffectiveRevision proves the success path: the
// candidate serves, the effective revision is reported, and the fleet is told.
func TestReplaceActivatesAndPublishesEffectiveRevision(t *testing.T) {
	fixture := newReplaceTestFixture(t)
	previous := fixture.configure(t, "a", "/opt/prev", nil)
	publisher := &replaceTestPublisher{}
	replacer := &Replacer{Registry: fixture.registry, Publisher: publisher}

	result, err := replacer.Replace(context.Background(), ReplaceRequest{AdapterID: "a", Executable: candidateFile(t, "next", 0o755, "x")})
	if err != nil {
		t.Fatalf("replace failed: %v", err)
	}
	if result.PreviousVersion != "prev" || result.EffectiveVersion != "next" || result.EffectiveRevision != "rev-next" {
		t.Fatalf("unexpected versions: %#v", result)
	}
	if result.Reverted {
		t.Fatalf("successful activation reported as reverted: %#v", result)
	}
	serving, ok := fixture.registry.Get("a")
	if !ok || serving == previous {
		t.Fatal("candidate is not serving after a successful activation")
	}
	if got := publisher.published(); len(got) != 1 || got[0] != "fixture" {
		t.Fatalf("capabilities were not republished exactly once: %v", got)
	}
	if previous.closeCount() != 1 {
		// Nothing held the previous version, so the swap closes it immediately. The
		// count proves it was closed exactly once: not leaked, and not closed twice.
		t.Fatalf("previous version close count = %d, want 1", previous.closeCount())
	}
}

// TestReplaceRevertsWhenPublicationFails proves the observable outcome is either
// "new version active and published" or "previous version active": a failed
// republish restores the previous version instead of leaving an unpublished
// candidate serving.
func TestReplaceRevertsWhenPublicationFails(t *testing.T) {
	fixture := newReplaceTestFixture(t)
	previous := fixture.configure(t, "a", "/opt/prev", nil)
	publisher := &replaceTestPublisher{err: errors.New("collector rejected the report")}
	replacer := &Replacer{Registry: fixture.registry, Publisher: publisher}

	result, err := replacer.Replace(context.Background(), ReplaceRequest{AdapterID: "a", Executable: candidateFile(t, "next", 0o755, "x")})
	if err == nil || !strings.Contains(err.Error(), "publish effective revision") {
		t.Fatalf("publication failure was not reported: %v", err)
	}
	if !result.Reverted {
		t.Fatalf("publication failure did not revert: %#v", result)
	}
	if result.EffectiveVersion != "prev" || result.EffectiveRevision != "rev-prev" {
		t.Fatalf("reverted result does not name the serving version: %#v", result)
	}
	// Nothing held the previous version, so it was closed at swap time and the
	// revert rebuilds it from its configuration. The serving version must therefore
	// be the previous version by identity, not the rejected candidate.
	serving, ok := fixture.registry.Get("a")
	if !ok {
		t.Fatal("no adapter is serving after a publication failure")
	}
	descriptor, err := serving.Describe(context.Background())
	if err != nil {
		t.Fatalf("describe serving adapter: %v", err)
	}
	if descriptor.Version != "prev" {
		t.Fatalf("serving version = %q, want prev", descriptor.Version)
	}
	if serving == previous {
		t.Fatal("closed previous instance was reinstated instead of rebuilt")
	}
}

// TestReplaceRevertsWithoutPublisher proves a missing publisher is treated as a
// publication failure rather than silently leaving an unpublished candidate.
func TestReplaceRevertsWithoutPublisher(t *testing.T) {
	fixture := newReplaceTestFixture(t)
	previous := fixture.configure(t, "a", "/opt/prev", nil)
	replacer := &Replacer{Registry: fixture.registry}

	result, err := replacer.Replace(context.Background(), ReplaceRequest{AdapterID: "a", Executable: candidateFile(t, "next", 0o755, "x")})
	if err == nil || !strings.Contains(err.Error(), "no descriptor publisher") {
		t.Fatalf("missing publisher was not reported: %v", err)
	}
	if !result.Reverted {
		t.Fatalf("missing publisher did not revert: %#v", result)
	}
	// The previous version was closed at swap time because nothing held it, so the
	// revert rebuilds it. Assert the serving version by identity of version, not by
	// pointer, and prove the closed instance was not reinstated.
	serving, ok := fixture.registry.Get("a")
	if !ok {
		t.Fatal("no adapter is serving without a publisher")
	}
	descriptor, err := serving.Describe(context.Background())
	if err != nil {
		t.Fatalf("describe serving adapter: %v", err)
	}
	if descriptor.Version != "prev" {
		t.Fatalf("serving version = %q, want prev", descriptor.Version)
	}
	if serving == previous {
		t.Fatal("closed previous instance was reinstated instead of rebuilt")
	}
}

// TestReplaceLeavesOtherAdaptersUntouched proves activation is per-adapter: a
// second adapter keeps its own instance and is never closed.
func TestReplaceLeavesOtherAdaptersUntouched(t *testing.T) {
	fixture := newReplaceTestFixture(t)
	first := fixture.configure(t, "a", "/opt/a-prev", nil)
	second := fixture.configure(t, "b", "/opt/b-prev", nil)
	replacer := &Replacer{Registry: fixture.registry, Publisher: &replaceTestPublisher{}}

	if _, err := replacer.Replace(context.Background(), ReplaceRequest{AdapterID: "a", Executable: candidateFile(t, "a-next", 0o755, "x")}); err != nil {
		t.Fatalf("replace failed: %v", err)
	}
	serving, ok := fixture.registry.Get("b")
	if !ok || serving != second {
		t.Fatal("unrelated adapter was replaced")
	}
	if second.closeCount() != 0 {
		t.Fatalf("unrelated adapter was closed: closes=%d", second.closeCount())
	}
	if first.closeCount() != 1 {
		// The replaced adapter had no callers, so it is closed exactly once. The
		// unrelated adapter above must still be at zero, which is what proves the
		// replacement was scoped to one adapter ID.
		t.Fatalf("replaced adapter close count = %d, want 1", first.closeCount())
	}
}

// TestReplaceReportsInFlightWork proves activation reports draining work instead
// of claiming an immediate clean handover.
func TestReplaceReportsInFlightWork(t *testing.T) {
	fixture := newReplaceTestFixture(t)
	fixture.configure(t, "a", "/opt/prev", nil)
	held, release, ok := fixture.registry.Acquire("a")
	if !ok {
		t.Fatal("acquire failed")
	}
	defer release()
	replacer := &Replacer{Registry: fixture.registry, Publisher: &replaceTestPublisher{}}

	result, err := replacer.Replace(context.Background(), ReplaceRequest{AdapterID: "a", Executable: candidateFile(t, "next", 0o755, "x")})
	if err != nil {
		t.Fatalf("replace failed: %v", err)
	}
	if result.InFlight != 1 {
		t.Fatalf("in-flight work not reported: %#v", result)
	}
	if held == nil {
		t.Fatal("held instance is nil")
	}
}

// TestReplaceRejectsDigestMismatchBeforeBootstrap proves a pinned digest is
// checked before the candidate is executed, so a tampered file is never run.
func TestReplaceRejectsDigestMismatchBeforeBootstrap(t *testing.T) {
	fixture := newReplaceTestFixture(t)
	previous := fixture.configure(t, "a", "/opt/prev", nil)
	replacer := &Replacer{Registry: fixture.registry, Publisher: &replaceTestPublisher{}}
	before := fixture.count()

	_, err := replacer.Replace(context.Background(), ReplaceRequest{
		AdapterID:      "a",
		Executable:     candidateFile(t, "next", 0o755, "x"),
		ExpectedSHA256: strings.Repeat("a", 64),
	})
	if err == nil || !strings.Contains(err.Error(), "does not match the expected") {
		t.Fatalf("tampered candidate accepted: %v", err)
	}
	if fixture.count() != before {
		t.Fatal("candidate was constructed despite a digest mismatch")
	}
	serving, ok := fixture.registry.Get("a")
	if !ok || serving != previous {
		t.Fatal("previous version is not serving after a digest mismatch")
	}
}
