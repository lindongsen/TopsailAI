package genericcli

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/commandexec"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/providercli"
)

// recordingCommandRunner captures the exact argv, executable and directory the
// adapter asked for, so a test can prove where the command would have run without
// running a real program.
type recordingCommandRunner struct {
	calls      int
	executable string
	argv       []string
	dir        string
	outcome    commandexec.Outcome
	err        error
}

func (r *recordingCommandRunner) Run(_ context.Context, executable string, argv []string, dir string) (commandexec.Outcome, error) {
	r.calls++
	r.executable = executable
	r.argv = argv
	r.dir = dir
	return r.outcome, r.err
}

// commandExecAdapter builds an adapter whose provider reports one session in a
// real temporary directory, so the directory resolution succeeds for a reason
// other than a hardcoded path.
func commandExecAdapter(t *testing.T, provider *fakeRunner, commands *recordingCommandRunner) (*Adapter, string) {
	t.Helper()
	directory := t.TempDir()
	resolved, err := filepath.EvalSymlinks(directory)
	if err != nil {
		t.Fatalf("resolve temp dir: %v", err)
	}
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		switch request.Function {
		case providercli.FunctionInspect:
			observation := providercli.ProviderObservation{
				ProviderResourceKey: "session:stable",
				ProviderGeneration:  "generation-1",
				ResourceKind:        protocol.ResourceSession,
				State:               "running",
				ObservedAtMS:        10,
				Attributes:          json.RawMessage(`{"provider_session_id":"session:stable","provider_project_workspace":"` + resolved + `"}`),
			}
			return providercli.Response{Version: request.Version, RequestID: request.RequestID, OK: true,
				Inspection: &providercli.InspectionResult{Found: true, Live: true, Observation: &observation}}, nil
		}
		// Inspect must be advertised, otherwise the adapter refuses the call as an
		// unsupported function before the directory can be read.
		return describeResponseWithFunctions(request, providercli.FunctionInspect), nil
	}
	limits := providercli.ConcurrencyLimits{Total: 2, Discovery: 1, Mutation: 1, Follow: 1}
	mapper := &fakeMapper{mappings: map[string]adapter.ResourceMapping{}}
	mapping, err := mapper.GetOrCreateResourceID(context.Background(), "a", protocol.ResourceSession, "session:stable", 10)
	if err != nil {
		t.Fatalf("seed mapping: %v", err)
	}
	config := Config{
		AdapterID: "a", DisplayName: "A", Timeout: time.Second,
		MaxStdinBytes: 65536, MaxStdoutBytes: 65536, MaxStderrBytes: 4096, MaxRecords: 10,
		EndpointLimits: limits, AdapterLimits: limits, Mapper: mapper,
		Capabilities:  protocol.CapabilityDescriptor{Revision: "r", Capabilities: []protocol.Capability{{Name: protocol.OperationCommandExec, Version: protocol.CommandExecPayloadVersion}}},
		CommandRunner: commands,
	}
	binding, err := newWithRunner(context.Background(), config, runnerAdapter{provider})
	if err != nil {
		t.Fatalf("new adapter: %v", err)
	}
	return binding, mapping.ResourceID
}

// TestExecuteRunsCommandExecWithoutInvokingTheProvider proves command.exec is
// Endpoint-native: the provider is inspected for the session directory but never
// asked to execute, because the Endpoint owns the allowlist, the confinement
// decision and the exact-process cleanup.
func TestExecuteRunsCommandExecWithoutInvokingTheProvider(t *testing.T) {
	provider := newFakeProvider(t)
	commands := &recordingCommandRunner{outcome: commandexec.Outcome{Stdout: []byte("/work\n"), ExitCode: 0}}
	binding, resourceID := commandExecAdapter(t, provider, commands)
	payload, err := json.Marshal(protocol.CommandExecRequest{Argv: []string{"pwd"}})
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	result, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
		CommandID: "cmd-1", Operation: protocol.OperationCommandExec, OperationVersion: protocol.CommandExecPayloadVersion,
		Payload: payload, Target: &protocol.CommandTarget{ResourceID: resourceID, Kind: protocol.ResourceSession},
		Budget: protocol.Budget{CLITimeoutMS: 5000}, ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli(),
	}})
	if err != nil {
		t.Fatalf("execute command.exec: %v", err)
	}
	if commands.calls != 1 {
		t.Fatalf("local command runs = %d, want 1", commands.calls)
	}
	if commands.argv[0] != "pwd" {
		t.Fatalf("argv = %v, want the operator argv", commands.argv)
	}
	if commands.dir == "" {
		t.Fatal("command ran without a resolved session directory")
	}
	for _, request := range provider.requests {
		if request.Function == providercli.FunctionExecute {
			t.Fatalf("command.exec was forwarded to the provider as %s", request.Operation.Name)
		}
	}
	if result.Receipt.ExitConfirmed != true || result.Receipt.EffectCertainty != protocol.EffectAcknowledged {
		t.Fatalf("receipt = %+v, want an acknowledged confirmed exit", result.Receipt)
	}
}

// TestExecuteFallsBackToTheProviderPwd proves the second directory candidate
// reaches the command runner.
//
// A session whose project workspace is absent on this host still reports the
// directory it was started from. The adapter must decode that value and let the
// resolver fall back to it, otherwise the command is refused even though the
// provider named a usable directory. The assertion is on the directory the runner
// received, because a test that only checked the decoded field would pass while the
// call site still passed one candidate.
func TestExecuteFallsBackToTheProviderPwd(t *testing.T) {
	provider := newFakeProvider(t)
	commands := &recordingCommandRunner{outcome: commandexec.Outcome{Stdout: []byte("ok\n"), ExitCode: 0}}
	binding, resourceID := commandExecAdapter(t, provider, commands)
	pwd := t.TempDir()
	resolvedPwd, err := filepath.EvalSymlinks(pwd)
	if err != nil {
		t.Fatalf("resolve temp dir: %v", err)
	}
	absent := filepath.Join(t.TempDir(), "absent-project")
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionInspect {
			observation := providercli.ProviderObservation{
				ProviderResourceKey: "session:stable", ProviderGeneration: "generation-1",
				ResourceKind: protocol.ResourceSession, State: "running", ObservedAtMS: 10,
				Attributes: json.RawMessage(`{"provider_session_id":"session:stable","provider_project_workspace":"` + absent + `","provider_pwd":"` + resolvedPwd + `"}`),
			}
			return providercli.Response{Version: request.Version, RequestID: request.RequestID, OK: true,
				Inspection: &providercli.InspectionResult{Found: true, Live: true, Observation: &observation}}, nil
		}
		return describeResponseWithFunctions(request, providercli.FunctionInspect), nil
	}
	payload, err := json.Marshal(protocol.CommandExecRequest{Argv: []string{"pwd"}})
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	result, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
		CommandID: "cmd-pwd", Operation: protocol.OperationCommandExec, OperationVersion: protocol.CommandExecPayloadVersion,
		Payload: payload, Target: &protocol.CommandTarget{ResourceID: resourceID, Kind: protocol.ResourceSession},
		Budget: protocol.Budget{CLITimeoutMS: 5000}, ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli(),
	}})
	if err != nil {
		t.Fatalf("execute command.exec: %v", err)
	}
	if commands.calls != 1 {
		t.Fatalf("local command runs = %d, want 1", commands.calls)
	}
	if commands.dir != resolvedPwd {
		t.Fatalf("directory = %q, want the provider pwd %q", commands.dir, resolvedPwd)
	}
	if result.Receipt.ExitConfirmed != true {
		t.Fatalf("receipt = %+v", result.Receipt)
	}
}

// TestExecuteRefusesCommandExecWithoutAProviderWorkspace proves the directory is
// provider evidence rather than a local guess: when the provider reports no
// workspace the command is refused instead of running in the Endpoint's own
// working directory.
func TestExecuteRefusesCommandExecWithoutAProviderWorkspace(t *testing.T) {
	provider := newFakeProvider(t)
	commands := &recordingCommandRunner{}
	binding, resourceID := commandExecAdapter(t, provider, commands)
	provider.invoke = func(request providercli.Request) (providercli.Response, error) {
		if request.Function == providercli.FunctionInspect {
			observation := providercli.ProviderObservation{
				ProviderResourceKey: "session:stable", ProviderGeneration: "generation-1",
				ResourceKind: protocol.ResourceSession, State: "running", ObservedAtMS: 10,
				Attributes: json.RawMessage(`{"provider_session_id":"session:stable"}`),
			}
			return providercli.Response{Version: request.Version, RequestID: request.RequestID, OK: true,
				Inspection: &providercli.InspectionResult{Found: true, Live: true, Observation: &observation}}, nil
		}
		return describeResponseWithFunctions(request, providercli.FunctionInspect), nil
	}
	payload, err := json.Marshal(protocol.CommandExecRequest{Argv: []string{"pwd"}})
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	result, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
		CommandID: "cmd-2", Operation: protocol.OperationCommandExec, OperationVersion: protocol.CommandExecPayloadVersion,
		Payload: payload, Target: &protocol.CommandTarget{ResourceID: resourceID, Kind: protocol.ResourceSession},
		Budget: protocol.Budget{CLITimeoutMS: 5000}, ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli(),
	}})
	if err == nil {
		t.Fatal("command.exec without a provider workspace was accepted")
	}
	if commands.calls != 0 {
		t.Fatalf("local command runs = %d, want 0", commands.calls)
	}
	if result.Receipt.ErrorCode != "session_directory_unavailable" || result.Receipt.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("receipt = %+v, want a not-applied directory refusal", result.Receipt)
	}
}

// TestExecuteRefusesCommandExecWithAnAbsoluteArgument proves the confinement
// decision happens before the command runs, so an argument addressing a fixed
// location outside the session directory never reaches the runner.
func TestExecuteRefusesCommandExecWithAnAbsoluteArgument(t *testing.T) {
	provider := newFakeProvider(t)
	commands := &recordingCommandRunner{}
	binding, resourceID := commandExecAdapter(t, provider, commands)
	payload, err := json.Marshal(protocol.CommandExecRequest{Argv: []string{"cat", "/etc/passwd"}})
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	result, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
		CommandID: "cmd-3", Operation: protocol.OperationCommandExec, OperationVersion: protocol.CommandExecPayloadVersion,
		Payload: payload, Target: &protocol.CommandTarget{ResourceID: resourceID, Kind: protocol.ResourceSession},
		Budget: protocol.Budget{CLITimeoutMS: 5000}, ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli(),
	}})
	if err == nil {
		t.Fatal("an absolute argument was accepted")
	}
	if commands.calls != 0 {
		t.Fatalf("local command runs = %d, want 0", commands.calls)
	}
	if result.Receipt.ErrorCode != "argument_not_confined" {
		t.Fatalf("receipt = %+v, want argument_not_confined", result.Receipt)
	}
}

// TestSessionDirectoryRejectsARelativeWorkspace proves the resolver fails closed
// rather than resolving a relative path against the Endpoint's own directory.
func TestSessionDirectoryRejectsARelativeWorkspace(t *testing.T) {
	if _, err := commandexec.SessionDirectory("relative/path", ""); err == nil {
		t.Fatal("a relative workspace was accepted")
	}
	if _, err := commandexec.SessionDirectory("", ""); err == nil {
		t.Fatal("an empty workspace was accepted")
	}
	file := filepath.Join(t.TempDir(), "not-a-directory")
	if err := os.WriteFile(file, []byte("x"), 0o600); err != nil {
		t.Fatalf("write file: %v", err)
	}
	if _, err := commandexec.SessionDirectory(file, ""); err == nil {
		t.Fatal("a regular file was accepted as a session directory")
	}
}

// commandExecEndpointAdapter builds an adapter for the endpoint-scope form, which
// carries no target and therefore resolves its directory from Endpoint
// configuration instead of from provider evidence.
//
// The command directory is a parameter because the two cases under test differ
// only in that value: an empty directory must be refused, and a configured one
// must run. A helper that hardcoded either value could only prove one half.
func commandExecEndpointAdapter(t *testing.T, provider *fakeRunner, commands *recordingCommandRunner, commandDir string) *Adapter {
	t.Helper()
	limits := providercli.ConcurrencyLimits{Total: 2, Discovery: 1, Mutation: 1, Follow: 1}
	config := Config{
		AdapterID: "a", DisplayName: "A", Timeout: time.Second,
		MaxStdinBytes: 65536, MaxStdoutBytes: 65536, MaxStderrBytes: 4096, MaxRecords: 10,
		EndpointLimits: limits, AdapterLimits: limits,
		Mapper:        &fakeMapper{mappings: map[string]adapter.ResourceMapping{}},
		Capabilities:  protocol.CapabilityDescriptor{Revision: "r", Capabilities: []protocol.Capability{{Name: protocol.OperationCommandExec, Version: protocol.CommandExecPayloadVersion}}},
		CommandRunner: commands,
		CommandDir:    commandDir,
	}
	binding, err := newWithRunner(context.Background(), config, runnerAdapter{provider})
	if err != nil {
		t.Fatalf("new adapter: %v", err)
	}
	return binding
}

// TestExecuteRefusesEndpointCommandExecWithoutACommandDirectory proves the
// endpoint-scope form reports its own refusal code rather than the session one.
//
// The two directory sources are different authorities. A session directory comes
// from provider evidence, so its absence is a fact about that session. The
// Endpoint directory comes from Endpoint configuration, so its absence is a
// setting the operator must supply. Reporting session_directory_unavailable for
// this form named a session directory the request never addressed, which sent the
// investigation to the wrong component and hid the setting that was missing.
func TestExecuteRefusesEndpointCommandExecWithoutACommandDirectory(t *testing.T) {
	provider := newFakeProvider(t)
	commands := &recordingCommandRunner{}
	binding := commandExecEndpointAdapter(t, provider, commands, "")
	payload, err := json.Marshal(protocol.CommandExecRequest{Argv: []string{"ls"}})
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	result, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
		CommandID: "cmd-endpoint-1", Operation: protocol.OperationCommandExec, OperationVersion: protocol.CommandExecPayloadVersion,
		Payload: payload, Target: nil,
		Budget: protocol.Budget{CLITimeoutMS: 5000}, ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli(),
	}})
	if err == nil {
		t.Fatal("the endpoint form ran without a configured command directory")
	}
	if commands.calls != 0 {
		t.Fatalf("local command runs = %d, want 0", commands.calls)
	}
	if result.Receipt.ErrorCode != protocol.CommandDirectoryUnavailable {
		t.Fatalf("receipt = %+v, want %q", result.Receipt, protocol.CommandDirectoryUnavailable)
	}
	if result.Receipt.ErrorCode == protocol.CommandSessionDirectoryUnavailable {
		t.Fatal("the endpoint form reported a session directory it never addressed")
	}
	if result.Receipt.EffectCertainty != protocol.EffectNotApplied {
		t.Fatalf("effect certainty = %q, want not applied", result.Receipt.EffectCertainty)
	}
}

// TestExecuteRunsEndpointCommandExecInTheConfiguredDirectory proves the endpoint
// form is reachable, not merely refused.
//
// Without this case the refusal test above would pass for an implementation that
// rejected every endpoint-scope request, which is the defect the issue reported.
// The assertion is on the directory the runner received, because a test that only
// checked the receipt would pass while the call site still passed an empty path.
func TestExecuteRunsEndpointCommandExecInTheConfiguredDirectory(t *testing.T) {
	provider := newFakeProvider(t)
	commands := &recordingCommandRunner{outcome: commandexec.Outcome{Stdout: []byte("ok\n"), ExitCode: 0}}
	directory := t.TempDir()
	resolved, err := filepath.EvalSymlinks(directory)
	if err != nil {
		t.Fatalf("resolve temp dir: %v", err)
	}
	binding := commandExecEndpointAdapter(t, provider, commands, resolved)
	payload, err := json.Marshal(protocol.CommandExecRequest{Argv: []string{"ls"}})
	if err != nil {
		t.Fatalf("marshal payload: %v", err)
	}
	result, err := binding.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{
		CommandID: "cmd-endpoint-2", Operation: protocol.OperationCommandExec, OperationVersion: protocol.CommandExecPayloadVersion,
		Payload: payload, Target: nil,
		Budget: protocol.Budget{CLITimeoutMS: 5000}, ExecuteBeforeAtMS: time.Now().Add(time.Minute).UnixMilli(),
	}})
	if err != nil {
		t.Fatalf("execute endpoint command.exec: %v", err)
	}
	if commands.calls != 1 {
		t.Fatalf("local command runs = %d, want 1", commands.calls)
	}
	if commands.dir != resolved {
		t.Fatalf("directory = %q, want the configured %q", commands.dir, resolved)
	}
	if result.Receipt.ExitConfirmed != true {
		t.Fatalf("receipt = %+v, want a confirmed exit", result.Receipt)
	}
}
