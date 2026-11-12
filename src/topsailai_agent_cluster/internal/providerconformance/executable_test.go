package providerconformance

import (
	"context"
	"encoding/json"
	"os"
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
)

func TestMockProviderDefaultConformance(t *testing.T) {
	runner := mockRunner(t, "")
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

	for _, function := range []string{
		providercli.FunctionInspect,
		providercli.FunctionExecute,
		providercli.FunctionQuery,
		providercli.FunctionQueryCommand,
		providercli.FunctionReadOutput,
	} {
		response := invoke(t, runner, requestFor(function))
		if !response.OK {
			t.Fatalf("%s returned %#v", function, response.Error)
		}
	}
	frames, _, err := runner.InvokeStream(context.Background(), requestFor(providercli.FunctionFollowOutput))
	if err != nil {
		t.Fatalf("follow output: %v", err)
	}
	if len(frames) != 3 || frames[0].Type != providercli.FrameStarted || frames[2].Type != providercli.FrameEnd {
		t.Fatalf("follow frames=%#v", frames)
	}
}

func TestMockProviderTypedQueryConformance(t *testing.T) {
	runner := mockRunner(t, "")
	for _, query := range providercli.StandardQueries() {
		t.Run(query.Name, func(t *testing.T) {
			request := requestFor(providercli.FunctionQuery)
			request.Query = &providercli.NamedContract{Name: query.Name, Version: query.Version}
			switch query.Name {
			case providercli.QueryModelCatalog, providercli.QuerySessionMessages:
				request.Target = &providercli.Target{ResourceKind: providercli.ResourceSession, ProviderResourceKey: "session:stable"}
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

func TestMockProviderUnsupportedFunction(t *testing.T) {
	response, _, err := mockRunner(t, "").Invoke(context.Background(), requestFor(providercli.FunctionWatch))
	if err != nil {
		t.Fatal(err)
	}
	if response.OK || response.Error == nil || response.Error.Code != "unsupported" {
		t.Fatalf("watch response=%#v", response)
	}
}

func TestMockProviderProtocolFaults(t *testing.T) {
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
			runner := mockRunner(t, testCase.fault)
			_, _, err := runner.Invoke(context.Background(), requestFor(providercli.FunctionDescribe))
			if err == nil || !strings.Contains(err.Error(), testCase.match) {
				t.Fatalf("error=%v, want %q", err, testCase.match)
			}
		})
	}
}

func TestMockProviderStderrLimitIsLabeled(t *testing.T) {
	runner := mockRunner(t, "oversized-stderr")
	response, invocation, err := runner.Invoke(context.Background(), requestFor(providercli.FunctionDescribe))
	if err != nil {
		t.Fatal(err)
	}
	if !response.OK || !invocation.StderrTruncated || len(invocation.Stderr) != int(runner.config.MaxStderrBytes) {
		t.Fatalf("response=%#v invocation=%#v", response, invocation)
	}
}

func TestMockProviderTimeoutAndCancellation(t *testing.T) {
	t.Run("deadline", func(t *testing.T) {
		runner := mockRunner(t, "timeout")
		_, invocation, err := runner.Invoke(context.Background(), requestFor(providercli.FunctionDescribe))
		if err == nil || !strings.Contains(err.Error(), "invocation deadline") {
			t.Fatalf("error=%v", err)
		}
		assertReportedHelperGone(t, invocation.Stderr)
	})
	t.Run("cancellation", func(t *testing.T) {
		runner := mockRunner(t, "timeout")
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
	runner := mockRunner(t, "false-capability")
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
	runner := mockRunner(t, "generation-race")
	response, _, err := runner.Invoke(context.Background(), requestFor(providercli.FunctionExecute))
	if err != nil {
		t.Fatal(err)
	}
	if response.OK || response.Error == nil || response.Error.Code != "generation_mismatch" ||
		response.Error.EffectCertainty != providercli.EffectNotApplied {
		t.Fatalf("execute response=%#v", response)
	}
}

func TestMockProviderHelperLeakIsDetected(t *testing.T) {
	runner := mockRunner(t, "helper-leak")
	_, invocation, err := runner.Invoke(context.Background(), requestFor(providercli.FunctionDescribe))
	if err == nil || !strings.Contains(err.Error(), "helper leaked") {
		t.Fatalf("error=%v", err)
	}
	assertReportedHelperGone(t, invocation.Stderr)
}

func TestMockProviderStreamFaults(t *testing.T) {
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
			runner := mockRunner(t, testCase.fault)
			_, _, err := runner.InvokeStream(context.Background(), requestFor(providercli.FunctionFollowOutput))
			if err == nil || !strings.Contains(err.Error(), testCase.match) {
				t.Fatalf("error=%v, want %q", err, testCase.match)
			}
		})
	}
}

func TestMockProviderRejectsRemoteFaultSelection(t *testing.T) {
	executable := mockExecutable(t)
	document := requestFor(providercli.FunctionDescribe)
	encoded, err := json.Marshal(document)
	if err != nil {
		t.Fatal(err)
	}
	encoded = append(encoded[:len(encoded)-1], []byte(`,"fault_mode":"timeout"}`)...)
	runner := mockRunner(t, "")
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

func mockRunner(t *testing.T, fault string) *Runner {
	t.Helper()
	executable := mockExecutable(t)
	environment := []string{"PATH=" + os.Getenv("PATH")}
	if fault != "" {
		environment = append(environment, mockFaultEnvironment+"="+fault)
	}
	runner, err := NewRunner(Config{
		Executable:     executable,
		Environment:    environment,
		Timeout:        300 * time.Millisecond,
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

func mockExecutable(t *testing.T) string {
	t.Helper()
	value := os.Getenv(mockExecutableEnvironment)
	if value == "" {
		t.Skip(mockExecutableEnvironment + " is not set; run make test-conformance")
	}
	return value
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
		AdapterID:    "mock-main",
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
	case providercli.FunctionQuery:
		request.Query = &providercli.NamedContract{Name: providercli.QueryModelCatalog, Version: "v1"}
		request.Target = target
	case providercli.FunctionQueryCommand:
		request.InvocationID = "invocation-1"
	}
	return request
}
