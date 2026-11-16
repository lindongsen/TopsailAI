package providerconformance

import (
	"context"
	"encoding/json"
	"os"
	"path/filepath"
	"regexp"
	"strconv"
	"strings"
	"testing"
	"time"

	"topsailai_agent_cluster/internal/providercli"
)

const (
	mockExecutableEnvironment = "AGENT_CLUSTER_MOCK_EXECUTABLE"
	mockFaultEnvironment      = "AGENT_CLUSTER_MOCK_FAULT"
	// mockMutationEnvironment names the file the Mock Provider appends one line
	// to per applied mutation, so a test can observe that a rejected execution
	// left no record.
	mockMutationEnvironment = "AGENT_CLUSTER_MOCK_MUTATION_FILE"
	// providerExecutableEnvironment selects any Provider CLI executable. When it
	// is unset the mock executable is used, so the mock target keeps its meaning.
	providerExecutableEnvironment = "AGENT_CLUSTER_PROVIDER_EXECUTABLE"
	// providerAdapterIDEnvironment supplies the adapter identity a Provider
	// expects in its request envelope. The mock default keeps that target
	// unchanged.
	providerAdapterIDEnvironment = "AGENT_CLUSTER_PROVIDER_ADAPTER_ID"
	// providerSessionIDEnvironment supplies the provider-private session
	// identifier the session.messages query addresses. A Provider that derives
	// its resource keys from a workspace row cannot accept a derived key there,
	// because that query takes a provider session ID.
	providerSessionIDEnvironment = "AGENT_CLUSTER_PROVIDER_SESSION_ID"
	// providerEnvironmentNames lists comma-separated variable names forwarded
	// from this process into the Provider process. A real Provider needs its own
	// business CLI configuration, and forwarding it by name keeps this package
	// free of provider-specific variable names.
	providerEnvironmentNames = "AGENT_CLUSTER_PROVIDER_ENVIRONMENT"
	// providerTimeoutEnvironment overrides the per-invocation timeout. The mock
	// answers immediately, while a real Provider may start a child process.
	providerTimeoutEnvironment = "AGENT_CLUSTER_PROVIDER_TIMEOUT_MS"

	defaultAdapterID = "mock-main"
	defaultSessionID = "session-1"
	defaultTimeoutMS = 300
)

func TestProviderDefaultConformance(t *testing.T) {
	runner := providerRunner(t, "")
	descriptorResponse := invoke(t, runner, requestFor(providercli.FunctionDescribe))
	if descriptorResponse.Descriptor == nil {
		t.Fatal("describe response has no descriptor")
	}
	if _, err := providercli.NegotiateVersion(descriptorResponse.Descriptor.ProtocolRange); err != nil {
		t.Fatalf("negotiate descriptor: %v", err)
	}

	first := invoke(t, runner, requestFor(providercli.FunctionDiscover))
	second := invoke(t, runner, requestFor(providercli.FunctionDiscover))
	if len(first.Discovery.Observations) != 1 || len(second.Discovery.Observations) != 1 {
		t.Fatal("discovery did not return one stable fixture")
	}
	firstObservation := first.Discovery.Observations[0]
	secondObservation := second.Discovery.Observations[0]
	if firstObservation.ProviderResourceKey != secondObservation.ProviderResourceKey ||
		firstObservation.ResourceKind != secondObservation.ResourceKind ||
		firstObservation.ProviderGeneration != secondObservation.ProviderGeneration {
		t.Fatalf("provider identity changed: %#v %#v", firstObservation, secondObservation)
	}

	// Only advertised functions are exercised. A Provider is not required to
	// implement every function the protocol defines, and demanding one it never
	// advertised would test this suite's assumptions instead of the contract.
	target := discoveredTarget(t, runner)
	for _, function := range descriptorResponse.Descriptor.Functions {
		switch function {
		case providercli.FunctionDescribe, providercli.FunctionDiscover, providercli.FunctionWatch:
			continue
		case providercli.FunctionFollowOutput:
			continue
		}
		response := invoke(t, runner, requestForTarget(function, target))
		if !response.OK {
			t.Fatalf("%s returned %#v", function, response.Error)
		}
	}
	frames, _, err := runner.InvokeStream(context.Background(), requestForTarget(providercli.FunctionFollowOutput, target))
	if err != nil {
		t.Fatalf("follow output: %v", err)
	}
	if len(frames) < 3 || frames[0].Type != providercli.FrameStarted || frames[len(frames)-1].Type != providercli.FrameEnd {
		t.Fatalf("follow frames=%#v", frames)
	}
}

func TestProviderTypedQueryConformance(t *testing.T) {
	runner := providerRunner(t, "")
	target := discoveredTarget(t, runner)
	for _, query := range providercli.StandardQueries() {
		t.Run(query.Name, func(t *testing.T) {
			request := requestFor(providercli.FunctionQuery)
			request.Query = &providercli.NamedContract{Name: query.Name, Version: query.Version}
			// The requirement is read from the registry rather than restated here.
			// A hardcoded list silently skipped every query it did not name, so a
			// newly registered session-scoped query was exercised with no target
			// and the Provider's correct rejection looked like a Provider defect.
			if providercli.QueryRequiresSessionTarget(query.Name) {
				key := providerSessionID()
				if query.Name == providercli.QueryModelCatalog {
					// The catalog read keeps addressing the discovered row key, so
					// row-key resolution stays covered; the other session reads
					// address the provider session identifier.
					key = target.key
				}
				request.Target = &providercli.Target{ResourceKind: providercli.ResourceSession, ProviderResourceKey: key}
			}
			response := invoke(t, runner, request)
			if _, err := providercli.DecodeQueryResult(providercli.NamedContract{Name: query.Name, Version: query.Version}, response.QueryResult); err != nil {
				t.Fatalf("decode typed query result: %v", err)
			}
			for _, forbidden := range []string{"launch_profile_id", "resource_id", "model_profile_id", "cluster_session_id", "command_id"} {
				if strings.Contains(string(response.QueryResult), `"`+forbidden+`"`) {
					t.Fatalf("query result contains Cluster-owned field %q: %s", forbidden, response.QueryResult)
				}
			}
		})
	}
}

func TestProviderUnsupportedFunction(t *testing.T) {
	response, _, err := providerRunner(t, "").Invoke(context.Background(), requestFor(providercli.FunctionWatch))
	if err != nil {
		t.Fatal(err)
	}
	if response.OK || response.Error == nil || response.Error.Code != "unsupported" {
		t.Fatalf("watch response=%#v", response)
	}
}

func TestMockProviderProtocolFaults(t *testing.T) {
	requireMock(t)
	for _, testCase := range []struct {
		fault string
		match string
	}{
		{fault: "malformed-json", match: "decode provider response"},
		{fault: "empty-stdout", match: "EOF"},
		{fault: "stdout-banner", match: "invalid character"},
		{fault: "duplicate-response", match: "extra JSON document"},
		{fault: "wrong-request-id", match: "does not match"},
		{fault: "wrong-version", match: "unsupported provider protocol minor"},
		{fault: "exit-result-conflict", match: "exit/result conflict"},
		{fault: "oversized-stdout", match: "stdout byte limit exceeded"},
	} {
		t.Run(testCase.fault, func(t *testing.T) {
			runner := providerRunner(t, testCase.fault)
			_, _, err := runner.Invoke(context.Background(), requestFor(providercli.FunctionDescribe))
			if err == nil || !strings.Contains(err.Error(), testCase.match) {
				t.Fatalf("error=%v, want %q", err, testCase.match)
			}
		})
	}
}

func TestMockProviderStderrLimitIsLabeled(t *testing.T) {
	requireMock(t)
	runner := providerRunner(t, "oversized-stderr")
	response, invocation, err := runner.Invoke(context.Background(), requestFor(providercli.FunctionDescribe))
	if err != nil {
		t.Fatal(err)
	}
	if !response.OK || !invocation.StderrTruncated || len(invocation.Stderr) != int(runner.config.MaxStderrBytes) {
		t.Fatalf("response=%#v invocation=%#v", response, invocation)
	}
}

func TestMockProviderTimeoutAndCancellation(t *testing.T) {
	requireMock(t)
	t.Run("deadline", func(t *testing.T) {
		runner := providerRunner(t, "timeout")
		_, invocation, err := runner.Invoke(context.Background(), requestFor(providercli.FunctionDescribe))
		if err == nil || !strings.Contains(err.Error(), "invocation deadline") {
			t.Fatalf("error=%v", err)
		}
		assertReportedHelperGone(t, invocation.Stderr)
	})
	t.Run("cancellation", func(t *testing.T) {
		runner := providerRunner(t, "timeout")
		ctx, cancel := context.WithCancel(context.Background())
		time.AfterFunc(100*time.Millisecond, cancel)
		_, invocation, err := runner.Invoke(ctx, requestFor(providercli.FunctionDescribe))
		if err == nil || !strings.Contains(err.Error(), "context canceled") {
			t.Fatalf("error=%v", err)
		}
		assertReportedHelperGone(t, invocation.Stderr)
	})
}

func TestMockProviderFalseCapabilityIsDetected(t *testing.T) {
	requireMock(t)
	runner := providerRunner(t, "false-capability")
	descriptor := invoke(t, runner, requestFor(providercli.FunctionDescribe)).Descriptor
	advertised := false
	for _, query := range descriptor.Queries {
		if query.Name == providercli.QueryModelCatalog && query.Version == "v1" {
			advertised = true
		}
	}
	if !advertised {
		t.Fatal("fixture did not advertise model.catalog")
	}
	response, _, err := runner.Invoke(context.Background(), requestFor(providercli.FunctionQuery))
	if err != nil {
		t.Fatal(err)
	}
	if response.OK || response.Error == nil || response.Error.Code != "unsupported" {
		t.Fatalf("query response=%#v", response)
	}
}

func TestMockProviderGenerationRaceRejectsMutation(t *testing.T) {
	requireMock(t)
	// The marker file is the only observable proof that no mutation was applied.
	// The error code and the effect certainty are both the provider's own claim,
	// so a provider that reported not_applied after writing would pass a check
	// that read only those two fields.
	mutationFile := filepath.Join(t.TempDir(), "mutations.log")
	runner := providerRunnerWithMutationFile(t, "generation-race", mutationFile)
	response, _, err := runner.Invoke(context.Background(), requestForTarget(providercli.FunctionExecute, discoveredTarget(t, runner)))
	if err != nil {
		t.Fatal(err)
	}
	if response.OK || response.Error == nil || response.Error.Code != "generation_mismatch" ||
		response.Error.EffectCertainty != providercli.EffectNotApplied {
		t.Fatalf("execute response=%#v", response)
	}
	if data, readErr := os.ReadFile(mutationFile); readErr == nil && len(data) > 0 {
		t.Fatalf("a rejected execution recorded a mutation: %q", data)
	}

	// The control proves the marker is written when a mutation is applied. Without
	// it the absence assertion above would also pass on a mock that never writes.
	control := providerRunnerWithMutationFile(t, "", mutationFile)
	controlResponse, _, controlErr := control.Invoke(context.Background(), requestForTarget(providercli.FunctionExecute, discoveredTarget(t, control)))
	if controlErr != nil {
		t.Fatal(controlErr)
	}
	if !controlResponse.OK {
		t.Fatalf("the control execution did not succeed: %#v", controlResponse)
	}
	data, readErr := os.ReadFile(mutationFile)
	if readErr != nil || len(data) == 0 {
		t.Fatalf("the control execution recorded no mutation: err=%v data=%q", readErr, data)
	}
}

func TestMockProviderHelperLeakIsDetected(t *testing.T) {
	requireMock(t)
	runner := providerRunner(t, "helper-leak")
	_, invocation, err := runner.Invoke(context.Background(), requestFor(providercli.FunctionDescribe))
	if err == nil || !strings.Contains(err.Error(), "helper leaked") {
		t.Fatalf("error=%v", err)
	}
	assertReportedHelperGone(t, invocation.Stderr)
}

func TestMockProviderStreamFaults(t *testing.T) {
	requireMock(t)
	for _, testCase := range []struct {
		fault string
		match string
	}{
		{fault: "missing-terminal", match: "stream_interrupted"},
		{fault: "duplicate-terminal", match: "after terminal"},
		{fault: "post-terminal-record", match: "after terminal"},
		{fault: "stream-correlation", match: "does not match"},
		{fault: "record-overflow", match: "record limit exceeded"},
	} {
		t.Run(testCase.fault, func(t *testing.T) {
			runner := providerRunner(t, testCase.fault)
			_, _, err := runner.InvokeStream(context.Background(), requestFor(providercli.FunctionFollowOutput))
			if err == nil || !strings.Contains(err.Error(), testCase.match) {
				t.Fatalf("error=%v, want %q", err, testCase.match)
			}
		})
	}
}

func TestMockProviderRejectsRemoteFaultSelection(t *testing.T) {
	requireMock(t)
	executable := mockExecutable(t)
	document := requestFor(providercli.FunctionDescribe)
	encoded, err := json.Marshal(document)
	if err != nil {
		t.Fatal(err)
	}
	encoded = append(encoded[:len(encoded)-1], []byte(`,"fault_mode":"timeout"}`)...)
	runner := providerRunner(t, "")
	invocation, invokeErr := runner.invokeDocument(context.Background(), encoded)
	if invokeErr != nil {
		t.Fatal(invokeErr)
	}
	if invocation.ExitCode == 0 || !strings.Contains(string(invocation.Stderr), "unknown field") {
		t.Fatalf("executable=%s invocation=%#v", executable, invocation)
	}
}

func assertReportedHelperGone(t *testing.T, stderr []byte) {
	t.Helper()
	match := regexp.MustCompile(`helper_pid=(\d+)`).FindSubmatch(stderr)
	if len(match) != 2 {
		t.Fatalf("helper PID missing from stderr %q", stderr)
	}
	pid, err := strconv.Atoi(string(match[1]))
	if err != nil {
		t.Fatal(err)
	}
	if processAlive(pid) {
		t.Fatalf("helper process %d is still alive", pid)
	}
}

// providerTarget is one provider-private identity discovered from the Provider.
type providerTarget struct {
	key        string
	generation string
}

// discoveredTarget reads the provider identity from discovery instead of
// hardcoding it, so the same suite drives a Provider that derives its own keys.
func discoveredTarget(t *testing.T, runner *Runner) providerTarget {
	t.Helper()
	response := invoke(t, runner, requestFor(providercli.FunctionDiscover))
	if response.Discovery == nil || len(response.Discovery.Observations) == 0 {
		t.Fatal("discovery returned no observation to address")
	}
	observation := response.Discovery.Observations[0]
	return providerTarget{key: observation.ProviderResourceKey, generation: observation.ProviderGeneration}
}

// providerRunner builds one runner for the selected Provider executable.
func providerRunner(t *testing.T, fault string) *Runner {
	t.Helper()
	executable := providerExecutable(t)
	environment := []string{"PATH=" + os.Getenv("PATH")}
	for _, name := range forwardedEnvironmentNames() {
		if value := os.Getenv(name); value != "" {
			environment = append(environment, name+"="+value)
		}
	}
	if fault != "" {
		environment = append(environment, mockFaultEnvironment+"="+fault)
	}
	runner, err := NewRunner(Config{
		Executable:     executable,
		Environment:    environment,
		Timeout:        providerTimeout(),
		MaxStdinBytes:  64 << 10,
		MaxStdoutBytes: 64 << 10,
		MaxStderrBytes: 16 << 10,
		MaxRecords:     16,
	})
	if err != nil {
		t.Fatal(err)
	}
	return runner
}

// providerRunnerWithMutationFile builds a runner that also tells the Mock
// Provider where to record applied mutations. The path travels through the
// forwarded environment because Config carries no argv.
func providerRunnerWithMutationFile(t *testing.T, fault string, mutationFile string) *Runner {
	t.Helper()
	t.Setenv(mockMutationEnvironment, mutationFile)
	t.Setenv(providerEnvironmentNames, mockMutationEnvironment)
	return providerRunner(t, fault)
}

// providerExecutable resolves the executable under test.
//
// The explicit Provider variable wins, and the mock variable remains the
// fallback, so `make test-conformance` keeps driving the mock executable.
func providerExecutable(t *testing.T) string {
	t.Helper()
	if value := os.Getenv(providerExecutableEnvironment); value != "" {
		return value
	}
	return mockExecutable(t)
}

// requireMock skips a mock-only test when another Provider is under test.
//
// Fault injection is a property of the mock executable, so running these cases
// against a real Provider would assert a capability it never advertised.
func requireMock(t *testing.T) {
	t.Helper()
	if os.Getenv(providerExecutableEnvironment) != "" {
		t.Skip("mock-only fault injection; " + providerExecutableEnvironment + " selects another Provider")
	}
}

func mockExecutable(t *testing.T) string {
	t.Helper()
	value := os.Getenv(mockExecutableEnvironment)
	if value == "" {
		t.Skip(mockExecutableEnvironment + " is not set; run make test-conformance")
	}
	return value
}

func providerAdapterID() string {
	if value := os.Getenv(providerAdapterIDEnvironment); value != "" {
		return value
	}
	return defaultAdapterID
}

func providerSessionID() string {
	if value := os.Getenv(providerSessionIDEnvironment); value != "" {
		return value
	}
	return defaultSessionID
}

func providerTimeout() time.Duration {
	value := os.Getenv(providerTimeoutEnvironment)
	if value == "" {
		return time.Duration(defaultTimeoutMS) * time.Millisecond
	}
	parsed, err := strconv.Atoi(value)
	if err != nil || parsed <= 0 {
		return time.Duration(defaultTimeoutMS) * time.Millisecond
	}
	return time.Duration(parsed) * time.Millisecond
}

func forwardedEnvironmentNames() []string {
	raw := os.Getenv(providerEnvironmentNames)
	if raw == "" {
		return nil
	}
	names := make([]string, 0, 4)
	for _, candidate := range strings.Split(raw, ",") {
		if trimmed := strings.TrimSpace(candidate); trimmed != "" {
			names = append(names, trimmed)
		}
	}
	return names
}

func invoke(t *testing.T, runner *Runner, request providercli.Request) providercli.Response {
	t.Helper()
	response, _, err := runner.Invoke(context.Background(), request)
	if err != nil {
		t.Fatal(err)
	}
	return response
}

func requestFor(function string) providercli.Request {
	request := providercli.Request{
		Version: providercli.Version{
			Protocol: providercli.ProtocolName,
			Major:    providercli.ProtocolMajor,
			Minor:    providercli.ProtocolMinor,
		},
		RequestID:    "request-1",
		Function:     function,
		AdapterID:    providerAdapterID(),
		DeadlineAtMS: time.Now().Add(time.Minute).UnixMilli(),
		Budget: providercli.Budget{
			MaxStdoutBytes: 64 << 10,
			MaxStderrBytes: 16 << 10,
			MaxRecords:     16,
		},
		Payload: json.RawMessage(`{}`),
	}
	target := &providercli.Target{
		ResourceKind:        providercli.ResourceSession,
		ProviderResourceKey: "session:stable",
	}
	switch function {
	case providercli.FunctionInspect, providercli.FunctionReadOutput, providercli.FunctionFollowOutput:
		request.Target = target
	case providercli.FunctionExecute:
		target.ExpectedGeneration = "generation-1"
		request.Target = target
		request.InvocationID = "invocation-1"
		request.Operation = &providercli.NamedContract{Name: "message.send", Version: "v1"}
		request.Payload = json.RawMessage(`{"text":"conformance"}`)
	case providercli.FunctionQuery:
		// A query carries its own target rules: launch.options and
		// history.messages must not carry one, while model.catalog and
		// session.messages require a session target. The default request
		// therefore leaves the target unset and each caller supplies the one
		// its query contract requires.
		request.Query = &providercli.NamedContract{Name: providercli.QueryModelCatalog, Version: "v1"}
	case providercli.FunctionQueryCommand:
		request.InvocationID = "invocation-1"
	}
	return request
}

// requestForTarget builds one request that addresses a discovered provider identity.
func requestForTarget(function string, target providerTarget) providercli.Request {
	request := requestFor(function)
	switch function {
	case providercli.FunctionInspect, providercli.FunctionReadOutput, providercli.FunctionFollowOutput:
		request.Target = &providercli.Target{ResourceKind: providercli.ResourceSession, ProviderResourceKey: target.key}
	case providercli.FunctionExecute:
		request.Target = &providercli.Target{ResourceKind: providercli.ResourceSession, ProviderResourceKey: target.key, ExpectedGeneration: target.generation}
	case providercli.FunctionQuery:
		// model.catalog is the query that requires a session target, so it is the
		// one the advertised-function sweep can address with a discovered key.
		request.Query = &providercli.NamedContract{Name: providercli.QueryModelCatalog, Version: "v1"}
		request.Target = &providercli.Target{ResourceKind: providercli.ResourceSession, ProviderResourceKey: target.key}
	case providercli.FunctionResolve:
		// resolve carries no target: it mints the key for a session identifier the
		// Endpoint has not discovered, so the sweep supplies a plain identifier.
		request.Payload = json.RawMessage(`{"handle":"conformance-session"}`)
	}
	return request
}
