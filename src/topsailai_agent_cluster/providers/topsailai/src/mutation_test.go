package main

import (
	"context"
	"encoding/json"
	"errors"
	"os/exec"
	"reflect"
	"strings"
	"testing"
)

// authorityCall is the single workspace read every session authority check makes.
const authorityCall = "workspace\x00list\x00--json\x00--local"

// discoverCall is the workspace read discovery makes. It is authorityCall plus
// --include-runtime, because the periodic report carries the message counts a
// table renders. Keeping it a separate constant makes the difference explicit:
// discovery asks for more than an authority check needs, and a mutation must not
// inherit that extra work.
const discoverCall = "workspace\x00list\x00--json\x00--local\x00--include-runtime"

// inspectCall is the workspace read inspect makes. It deliberately omits --local,
// because resume authorizes on the absence of a live target and a --local read
// would report another host's session as missing.
const inspectCall = "workspace\x00list\x00--json"

// sessionAuthorityCall is the session registry read resume makes for a
// session-scoped target. It is deliberately not authorityCall: the workspace list
// cannot see a session that has no workspace row, so resume must read the registry
// the history query reads.
const sessionAuthorityCall = "project\x00list_sessions\x00--json"

// registryDocument reports one session registry entry.
func registryDocument(sessionID, status string) string {
	return `[{"session_id":"` + sessionID + `","status":"` + status + `"}]`
}

// mutationRequest builds one execute request for a standard operation.
func mutationRequest(operation string, target *target, payload string) request {
	value := validRequest(functionExecute)
	value.InvocationID = "invocation-1"
	value.Operation = &namedContract{Name: operation, Version: operationVersion}
	value.Target = target
	value.Payload = json.RawMessage(payload)
	return value
}

// liveSessionTarget returns the shared session target with one generation.
func liveSessionTarget(t *testing.T, generation string) *target {
	t.Helper()
	value := sessionTarget(t)
	value.ExpectedGeneration = generation
	return value
}

// launchProfileTarget returns the frozen launch profile target.
func launchProfileTarget(revision string) *target {
	return &target{ResourceKind: resourceLaunchProfile, ProviderResourceKey: launchProfileKey, ExpectedGeneration: revision}
}

// liveWorkspaceDocument reports the shared session row as a live process.
func liveWorkspaceDocument(generation string) string {
	return `{"items":[{"session_id":"s-1","filename":"row","pid":42,"process_generation":` + generation + `}]}`
}

// dormantWorkspaceDocument reports the shared session row without a generation.
func dormantWorkspaceDocument() string {
	return `{"items":[{"session_id":"s-1","filename":"row","pid":42}]}`
}

// exitErrorFromProcess returns a real *exec.ExitError so the outcome classifier is
// exercised with the error type a finished-but-failed child actually produces.
func exitErrorFromProcess(t *testing.T) error {
	t.Helper()
	err := exec.Command("sh", "-c", "exit 3").Run()
	var exitError *exec.ExitError
	if !errors.As(err, &exitError) {
		t.Fatalf("expected an exit error, got %v", err)
	}
	return exitError
}

// TestMutationArgvMatchesFixedProviderCommands pins every standard operation onto
// the exact provider argv the Cluster adapter already uses.
//
// Two spellings of one provider invocation would be two behaviours to keep in step,
// so the argv is asserted element by element rather than by prefix.
func TestMutationArgvMatchesFixedProviderCommands(t *testing.T) {
	session := liveSessionTarget(t, "7")
	tests := []struct {
		name      string
		operation string
		target    *target
		payload   string
		answers   map[string][]runnerAnswer
		want      []string
	}{
		{
			name:      "message send",
			operation: operationMessageSend,
			target:    session,
			payload:   `{"text":"hello"}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))},
			want:      []string{"runtime", "send", "-s", "s-1", "-m=hello", "--json"},
		},
		{
			name:      "context inject",
			operation: operationContextInject,
			target:    session,
			payload:   `{"message":"side context"}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))},
			want:      []string{"runtime", "btw", "-s", "s-1", "-m=side context", "--json"},
		},
		{
			name:      "agent stop",
			operation: operationAgentStop,
			target:    session,
			payload:   `{}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))},
			want:      []string{"workspace", "kill", "s-1", "-g", "7", "--json"},
		},
		{
			name:      "drive start",
			operation: operationAgentDriveStart,
			target:    session,
			payload:   `{}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))},
			want:      []string{"workspace", "driver", "start", "-s", "s-1", "--json"},
		},
		{
			name:      "drive stop",
			operation: operationAgentDriveStop,
			target:    session,
			payload:   `{}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(dormantWorkspaceDocument())},
			want:      []string{"workspace", "driver", "stop", "-s", "s-1", "--json"},
		},
		{
			name:      "agent resume",
			operation: operationAgentResume,
			target:    session,
			payload:   `{}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(dormantWorkspaceDocument())},
			want:      []string{"workspace", "resume", "-s", "s-1", "--background", "--json"},
		},
		{
			// A session-scoped target names the session, not one workspace row, so
			// resume must read the session registry. The workspace list cannot see a
			// session that has no workspace row, and reading it here is what reported
			// a resumable session as not found.
			name:      "agent resume by session handle",
			operation: operationAgentResume,
			target:    sessionScopedTarget(t, "s-1"),
			payload:   `{}`,
			answers:   map[string][]runnerAnswer{sessionAuthorityCall: answer(registryDocument("s-1", "Idle"))},
			want:      []string{"workspace", "resume", "-s", "s-1", "--background", "--json"},
		},
		{
			name:      "workspace clean",
			operation: operationWorkspaceClean,
			target:    session,
			payload:   `{}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(dormantWorkspaceDocument())},
			want:      []string{"workspace", "clean", "-s", "s-1", "-p", "42", "--yes", "--json"},
		},
		{
			name:      "agent start",
			operation: operationAgentStart,
			target:    launchProfileTarget(launchProfileRevision),
			payload:   `{"folder":"/work/demo","task":"do it"}`,
			answers:   map[string][]runnerAnswer{},
			want:      []string{"workspace", "agent", "/work/demo", "--background", "--json", "--non-interactive", "--task=do it"},
		},
		{
			name:      "model select",
			operation: operationAgentModelSelect,
			target:    session,
			payload:   `{"provider_resource_key":"model:fast"}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))},
			want:      []string{"runtime", "control", "call_instruction", "-s", "s-1", "-a", `{"args":["fast"],"instruction":"agent.models"}`, "--json"},
		},
		{
			name:      "hard interrupt",
			operation: operationExecutionInterrupt,
			target:    session,
			payload:   `{"action":"hard_interrupt"}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))},
			want:      []string{"runtime", "control", "hard_interrupt", "-s", "s-1", "-a", "{}", "--json"},
		},
		{
			name:      "soft interrupt with message",
			operation: operationExecutionInterrupt,
			target:    session,
			payload:   `{"action":"soft_interrupt","message":"wrap up"}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))},
			want:      []string{"runtime", "control", "soft_interrupt", "-s", "s-1", "-a", `{"message":"wrap up"}`, "--json"},
		},
		{
			name:      "soft interrupt without message",
			operation: operationExecutionInterrupt,
			target:    session,
			payload:   `{"action":"soft_interrupt"}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))},
			want:      []string{"runtime", "control", "soft_interrupt", "-s", "s-1", "-a", "{}", "--json"},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			answers := map[string][]runnerAnswer{}
			for key, value := range test.answers {
				answers[key] = value
			}
			answers[strings.Join(test.want, "\x00")] = answer(`{"ok":true}`)
			runner := &scriptedRunner{t: t, answers: answers}
			got := fixedProvider(runner).dispatch(context.Background(), mutationRequest(test.operation, test.target, test.payload))
			if !got.OK || got.Result == nil {
				t.Fatalf("response=%+v", got)
			}
			if len(runner.calls) == 0 {
				t.Fatal("no provider command ran")
			}
			last := runner.calls[len(runner.calls)-1].args
			if !reflect.DeepEqual(last, test.want) {
				t.Fatalf("argv=%v want %v", last, test.want)
			}
			if got.Result.ProviderOutcome != "succeeded" || got.Result.EffectCertainty != effectAcknowledged || got.Result.DeliveryBoundary != deliverySubmitted {
				t.Fatalf("result=%+v", got.Result)
			}
			if got.Result.ProviderRequestRef != "invocation-1" {
				t.Fatalf("provider_request_ref=%q", got.Result.ProviderRequestRef)
			}
		})
	}
}

// TestMutationAuthorityRejectsBeforeRunningBusinessCommand proves a rejected target
// never reaches the provider CLI.
//
// The scripted runner fails the test on any unexpected call, so a business argv that
// ran would be reported as an unexpected CLI call rather than silently passing.
func TestMutationAuthorityRejectsBeforeRunningBusinessCommand(t *testing.T) {
	tests := []struct {
		name      string
		operation string
		target    *target
		payload   string
		answers   map[string][]runnerAnswer
	}{
		{
			name:      "stale generation",
			operation: operationMessageSend,
			target:    liveSessionTarget(t, "7"),
			payload:   `{"text":"hello"}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("8"))},
		},
		{
			name:      "unverified liveness",
			operation: operationAgentStop,
			target:    liveSessionTarget(t, "7"),
			payload:   `{}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(dormantWorkspaceDocument())},
		},
		{
			name:      "missing row",
			operation: operationAgentDriveStop,
			target:    liveSessionTarget(t, "7"),
			payload:   `{}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(`{"items":[]}`)},
		},
		{
			name:      "duplicate row",
			operation: operationWorkspaceClean,
			target:    liveSessionTarget(t, "7"),
			payload:   `{}`,
			answers: map[string][]runnerAnswer{authorityCall: answer(
				`{"items":[{"session_id":"s-1","filename":"row","pid":42},{"session_id":"s-1","filename":"row","pid":42}]}`)},
		},
		{
			// A row-scoped key names one workspace row, which the session registry
			// cannot describe, so it keeps the workspace read and its live rejection.
			name:      "resume of a live row target",
			operation: operationAgentResume,
			target:    liveSessionTarget(t, "7"),
			payload:   `{}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))},
		},
		{
			// A session-scoped key that the registry does not list cannot be resumed,
			// and the rejection must happen before any business argv exists.
			name:      "resume of a session absent from the registry",
			operation: operationAgentResume,
			target:    sessionScopedTarget(t, "s-1"),
			payload:   `{}`,
			answers:   map[string][]runnerAnswer{sessionAuthorityCall: answer(registryDocument("s-2", "Idle"))},
		},
		{
			// Two registry entries for one session make the target ambiguous, so the
			// request must be refused rather than resolved to the first match.
			name:      "resume of a session listed twice",
			operation: operationAgentResume,
			target:    sessionScopedTarget(t, "s-1"),
			payload:   `{}`,
			answers: map[string][]runnerAnswer{sessionAuthorityCall: answer(
				`[{"session_id":"s-1","status":"Idle"},{"session_id":"s-1","status":"Idle"}]`)},
		},
		{
			name:      "stale launch profile revision",
			operation: operationAgentStart,
			target:    launchProfileTarget("topsailai-launch-v0"),
			payload:   `{"folder":"/work/demo"}`,
			answers:   map[string][]runnerAnswer{},
		},
		{
			name:      "unknown launch profile",
			operation: operationAgentStart,
			target:    &target{ResourceKind: resourceLaunchProfile, ProviderResourceKey: "other", ExpectedGeneration: launchProfileRevision},
			payload:   `{"folder":"/work/demo"}`,
			answers:   map[string][]runnerAnswer{},
		},
		{
			name:      "agent start without folder",
			operation: operationAgentStart,
			target:    launchProfileTarget(launchProfileRevision),
			payload:   `{"task":"do it"}`,
			answers:   map[string][]runnerAnswer{},
		},
		{
			name:      "model select with a non model key",
			operation: operationAgentModelSelect,
			target:    liveSessionTarget(t, "7"),
			payload:   `{"provider_resource_key":"fast"}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("7"))},
		},
		{
			// An interrupt addresses a live process, so it must prove which
			// process it reaches before any argv exists. This case is what
			// distinguishes the live-authority path from the non-live one: an
			// explicit branch that used requireNonLiveRecord would accept a
			// stale generation and run the provider control command against a
			// replacement process, and every other interrupt test would stay
			// green because they only assert the argv shape.
			name:      "interrupt with a stale generation",
			operation: operationExecutionInterrupt,
			target:    liveSessionTarget(t, "7"),
			payload:   `{"action":"hard_interrupt"}`,
			answers:   map[string][]runnerAnswer{authorityCall: answer(liveWorkspaceDocument("8"))},
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			runner := &scriptedRunner{t: t, answers: test.answers}
			got := fixedProvider(runner).dispatch(context.Background(), mutationRequest(test.operation, test.target, test.payload))
			if got.OK || got.Error == nil {
				t.Fatalf("response=%+v", got)
			}
			if got.Error.Code != "invalid_request" {
				t.Fatalf("error=%+v", got.Error)
			}
			if got.Result != nil {
				t.Fatalf("rejected request produced a result: %+v", got.Result)
			}
		})
	}
}

// TestMutationRequiresGenerationForLiveOperations pins the operation-sensitive rule.
//
// A live mutation without target evidence must be rejected before any read, because
// an empty generation cannot prove which process the operation would reach.
func TestMutationRequiresGenerationForLiveOperations(t *testing.T) {
	for _, operation := range []string{operationMessageSend, operationContextInject, operationAgentStop, operationAgentDriveStart, operationAgentModelSelect} {
		t.Run(operation, func(t *testing.T) {
			runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
			got := fixedProvider(runner).dispatch(context.Background(), mutationRequest(operation, sessionTarget(t), `{}`))
			if got.OK || got.Error == nil || got.Error.Code != "invalid_request" {
				t.Fatalf("response=%+v", got)
			}
			if len(runner.calls) != 0 {
				t.Fatalf("calls=%v", runner.calls)
			}
		})
	}
}

// TestNonLiveAuthorityOperationsArePinned pins the three frozen exceptions.
//
// The list mirrors protocol/provider-cli/v1/request.schema.json. This executable is
// an independent module, so the copy is unavoidable; the test is what stops the two
// copies from drifting apart silently.
func TestNonLiveAuthorityOperationsArePinned(t *testing.T) {
	want := []string{operationAgentResume, operationAgentDriveStop, operationWorkspaceClean}
	if got := nonLiveAuthorityOperations[:]; !reflect.DeepEqual(got, want) {
		t.Fatalf("non-live operations=%v want %v", got, want)
	}
	for _, operation := range want {
		if operationNeedsLiveGeneration(operation) {
			t.Fatalf("%s must not require a live generation", operation)
		}
	}
	for _, operation := range []string{operationAgentStart, operationMessageSend, "future.operation"} {
		if !operationNeedsLiveGeneration(operation) {
			t.Fatalf("%s must require a live generation", operation)
		}
	}
}

// TestMutationRejectsMalformedExecuteEnvelope covers the frozen request contract.
func TestMutationRejectsMalformedExecuteEnvelope(t *testing.T) {
	valid := mutationRequest(operationMessageSend, liveSessionTarget(t, "7"), `{"text":"hello"}`)
	tests := map[string]func(request) request{
		"missing invocation": func(value request) request { value.InvocationID = ""; return value },
		"missing operation":  func(value request) request { value.Operation = nil; return value },
		"missing target":     func(value request) request { value.Target = nil; return value },
		"wrong version": func(value request) request {
			value.Operation = &namedContract{Name: operationMessageSend, Version: "v2"}
			return value
		},
		"query present": func(value request) request {
			value.Query = &namedContract{Name: queryLaunchOptions, Version: queryVersion}
			return value
		},
		"unknown operation": func(value request) request {
			value.Operation = &namedContract{Name: "future.operation", Version: operationVersion}
			return value
		},
	}
	for name, mutate := range tests {
		t.Run(name, func(t *testing.T) {
			runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{}}
			got := fixedProvider(runner).dispatch(context.Background(), mutate(valid))
			if got.OK || got.Error == nil {
				t.Fatalf("response=%+v", got)
			}
			if len(runner.calls) != 0 {
				t.Fatalf("calls=%v", runner.calls)
			}
		})
	}
}

// TestMutationOutcomeEvidence pins the effect classification.
//
// An unknown effect is never upgraded to acknowledged, and a provider document that
// arrived on a failed exit is preserved instead of being flattened.
func TestMutationOutcomeEvidence(t *testing.T) {
	tests := []struct {
		name          string
		answer        runnerAnswer
		wantBoundary  string
		wantCertainty string
		wantOutcome   string
		wantResponse  string
		wantTruncated bool
	}{
		{
			name:          "success",
			answer:        runnerAnswer{stdout: `{"ok":true}`},
			wantBoundary:  deliverySubmitted,
			wantCertainty: effectAcknowledged,
			wantOutcome:   "succeeded",
			wantResponse:  `{"ok":true}`,
		},
		{
			name:          "failed exit with a provider document",
			answer:        runnerAnswer{stdout: `{"ok":false,"error_code":"rejected"}`, stderr: "noise", err: nil},
			wantBoundary:  deliverySubmitted,
			wantCertainty: effectAcknowledged,
			wantOutcome:   "failed",
			wantResponse:  `{"ok":false,"error_code":"rejected"}`,
		},
		{
			name:          "failed exit without a provider document",
			answer:        runnerAnswer{stdout: "plain text", stderr: "boom"},
			wantBoundary:  deliverySubmitted,
			wantCertainty: effectUnknown,
			wantOutcome:   "unconfirmed",
			wantResponse:  "boom",
		},
		{
			name:          "process never started",
			answer:        runnerAnswer{stderr: "exec: not found"},
			wantBoundary:  deliveryNotStarted,
			wantCertainty: effectNotApplied,
			wantOutcome:   "failed",
			wantResponse:  "exec: not found",
		},
	}
	for _, test := range tests {
		t.Run(test.name, func(t *testing.T) {
			answerValue := test.answer
			if test.name == "failed exit with a provider document" || test.name == "failed exit without a provider document" {
				answerValue.err = exitErrorFromProcess(t)
			}
			if test.name == "process never started" {
				answerValue.err = errors.New("exec: not found")
			}
			runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
				authorityCall: answer(liveWorkspaceDocument("7")),
				"runtime\x00send\x00-s\x00s-1\x00-m=hello\x00--json": {answerValue},
			}}
			got := fixedProvider(runner).dispatch(context.Background(), mutationRequest(operationMessageSend, liveSessionTarget(t, "7"), `{"text":"hello"}`))
			if !got.OK || got.Result == nil {
				t.Fatalf("response=%+v", got)
			}
			if got.Result.DeliveryBoundary != test.wantBoundary || got.Result.EffectCertainty != test.wantCertainty || got.Result.ProviderOutcome != test.wantOutcome {
				t.Fatalf("result=%+v", got.Result)
			}
			if got.Result.ProviderResponse != test.wantResponse || got.Result.ProviderResponseTruncated != test.wantTruncated {
				t.Fatalf("provider_response=%q truncated=%v", got.Result.ProviderResponse, got.Result.ProviderResponseTruncated)
			}
		})
	}
}

// TestMutationTruncatesOversizedProviderResponse proves a shortened provider answer
// is labelled instead of being presented as complete evidence.
func TestMutationTruncatesOversizedProviderResponse(t *testing.T) {
	document := `{"ok":true,"padding":"` + strings.Repeat("x", maxProviderResponseBytes) + `"}`
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		authorityCall: answer(liveWorkspaceDocument("7")),
		"runtime\x00send\x00-s\x00s-1\x00-m=hello\x00--json": answer(document),
	}}
	got := fixedProvider(runner).dispatch(context.Background(), mutationRequest(operationMessageSend, liveSessionTarget(t, "7"), `{"text":"hello"}`))
	if !got.OK || got.Result == nil {
		t.Fatalf("response=%+v", got)
	}
	if !got.Result.ProviderResponseTruncated {
		t.Fatal("oversized provider response was not labelled")
	}
	if len(got.Result.ProviderResponse) > maxProviderResponseBytes {
		t.Fatalf("provider_response length=%d", len(got.Result.ProviderResponse))
	}
}

// TestDescriptorOperationsMatchDispatch proves the advertised surface and the
// dispatchable surface are the same set.
func TestDescriptorOperationsMatchDispatch(t *testing.T) {
	contracts := mutationOperations(supportedPlatform)
	if len(contracts) != len(supportedMutationOperations) {
		t.Fatalf("contracts=%v", contracts)
	}
	for _, contract := range contracts {
		if contract.Version != operationVersion {
			t.Fatalf("contract=%+v", contract)
		}
		if !supportedMutationOperation(contract.Name, supportedPlatform) {
			t.Fatalf("%s is advertised but not dispatchable", contract.Name)
		}
	}
	if supportedMutationOperation("future.operation", supportedPlatform) {
		t.Fatal("an unimplemented operation is dispatchable")
	}
}

// TestAgentStartArgvRequestsBackgroundCustody pins the half of the custody
// contract this repository can prove. The Provider asks the business CLI to
// detach with --background, so the handoff is a background launch rather than a
// foreground one; whether the Agent then outlives the Provider CLI is a
// provider-runtime property no test here can observe, which is why the live
// custody smoke stays open.
func TestAgentStartArgvRequestsBackgroundCustody(t *testing.T) {
	args, err := agentStartArgs(json.RawMessage(`{"folder":"/work/demo","task":"do it"}`))
	if err != nil {
		t.Fatalf("agentStartArgs: %v", err)
	}
	if !containsArg(args, "--background") {
		t.Fatalf("agent.start argv = %v, want --background so the launch detaches", args)
	}
	resume, err := mutationArgs(mutationInvocation{
		Operation: operationAgentResume,
		Resolved:  providerSessionTarget{SessionID: "provider-session"},
	})
	if err != nil {
		t.Fatalf("mutationArgs resume: %v", err)
	}
	if !containsArg(resume, "--background") {
		t.Fatalf("agent.resume argv = %v, want --background so the resume detaches", resume)
	}
	resultType := reflect.TypeOf(operationResult{})
	for index := 0; index < resultType.NumField(); index++ {
		name := strings.ToLower(resultType.Field(index).Tag.Get("json"))
		for _, marker := range []string{"surviv", "durab", "liveness", "alive", "outliv", "persist"} {
			if strings.Contains(name, marker) {
				t.Fatalf("operationResult declares %q, which claims a custody property the protocol cannot carry", name)
			}
		}
	}
}

// containsArg reports whether argv carries the exact flag.
func containsArg(argv []string, flag string) bool {
	for _, value := range argv {
		if value == flag {
			return true
		}
	}
	return false
}

// TestInterruptArgsRejectsAnUnsupportedAction proves the interrupt action
// vocabulary is closed before any provider argv exists.
//
// The action names a provider instruction, so an unrecognized value would become an
// arbitrary instruction name if it were passed through. Rejecting it here keeps the
// Cluster contract the only source of accepted actions, and it means a typo is
// reported as an invalid payload instead of as a provider failure.
func TestInterruptArgsRejectsAnUnsupportedAction(t *testing.T) {
	for _, payload := range []string{
		`{"action":"clear_interrupt"}`,
		`{"action":""}`,
		`{}`,
		`{"action":"hard_interrupt","message":"not allowed"}`,
	} {
		if _, err := interruptArgs("s-1", json.RawMessage(payload)); err == nil {
			t.Fatalf("payload %s was accepted, want a rejection", payload)
		}
	}
}

// TestInterruptArgsSendsNoMessageDocumentWhenTheTextIsEmpty proves an empty soft
// interrupt carries no message field.
//
// An empty string has nothing to deliver, so sending `{"message":""}` would ask the
// provider to inject an empty message. Both an absent message and an empty one
// therefore produce the empty document, and the CLI already omits the field when the
// operator supplies no text.
func TestInterruptArgsSendsNoMessageDocumentWhenTheTextIsEmpty(t *testing.T) {
	for _, payload := range []string{
		`{"action":"soft_interrupt"}`,
		`{"action":"soft_interrupt","message":""}`,
	} {
		argv, err := interruptArgs("s-1", json.RawMessage(payload))
		if err != nil {
			t.Fatalf("payload %s: %v", payload, err)
		}
		if got := argv[len(argv)-2]; got != "{}" {
			t.Fatalf("payload %s document = %q, want {}", payload, got)
		}
	}
}

// TestResumeResolvesASessionThatOnlyTheRegistryLists pins the authority source.
//
// A persisted session can exist in the provider session registry with no workspace
// row, because the workspace list reports only rows this host can see and only rows
// that still have a workspace record. Reading the workspace list for resume therefore
// reported a session the provider can resume as not found, and the operator saw
// "provider session row was not found" for a row the history list had just shown.
//
// The registry is the read the history query uses, so a row the operator saw in
// history and a handle the operator typed resolve against one source. This test
// asserts both halves: the registry is read, and the workspace list is not.
func TestResumeResolvesASessionThatOnlyTheRegistryLists(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		sessionAuthorityCall: answer(registryDocument("s-1", "Idle")),
		strings.Join([]string{"workspace", "resume", "-s", "s-1", "--background", "--json"}, "\x00"): answer(`{"ok":true}`),
	}}
	got := fixedProvider(runner).dispatch(context.Background(), mutationRequest(operationAgentResume, sessionScopedTarget(t, "s-1"), `{}`))
	if !got.OK || got.Result == nil {
		t.Fatalf("response=%+v", got)
	}
	for _, call := range runner.calls {
		if strings.Join(call.args, "\x00") == authorityCall {
			t.Fatalf("resume read the workspace list: %v", call.args)
		}
	}
	if len(runner.calls) != 2 {
		t.Fatalf("calls=%v want the registry read and the resume argv", runner.calls)
	}
	if last := runner.calls[len(runner.calls)-1].args; !reflect.DeepEqual(last, []string{"workspace", "resume", "-s", "s-1", "--background", "--json"}) {
		t.Fatalf("argv=%v", last)
	}
}

// TestResumeDoesNotDecideLivenessForASessionHandle pins the authority split.
//
// The provider revalidates liveness twice in the resume path and refuses a live
// target itself, so a cluster-side rejection would duplicate that authority and
// would refuse exactly the sessions resume exists for. A session-scoped target
// therefore reaches the provider even when the registry reports it as running, and
// the provider's own refusal is what stops it.
func TestResumeDoesNotDecideLivenessForASessionHandle(t *testing.T) {
	runner := &scriptedRunner{t: t, answers: map[string][]runnerAnswer{
		sessionAuthorityCall: answer(registryDocument("s-1", "Running")),
		strings.Join([]string{"workspace", "resume", "-s", "s-1", "--background", "--json"}, "\x00"): []runnerAnswer{{
			stdout: `{"ok":false,"exit_code":4,"error_code":"resume_refused","response":{"startup_reason":"already_running"}}`,
			err:    exitErrorFromProcess(t),
		}},
	}}
	got := fixedProvider(runner).dispatch(context.Background(), mutationRequest(operationAgentResume, sessionScopedTarget(t, "s-1"), `{}`))
	if got.Result == nil {
		t.Fatalf("response=%+v", got)
	}
	if got.Result.ProviderOutcome != "failed" {
		t.Fatalf("provider_outcome=%q want failed", got.Result.ProviderOutcome)
	}
	if !strings.Contains(got.Result.ProviderResponse, "resume_refused") {
		t.Fatalf("provider_response=%q want the provider refusal document", got.Result.ProviderResponse)
	}
	if len(runner.calls) != 2 {
		t.Fatalf("calls=%v want the registry read and the resume argv", runner.calls)
	}
	if last := runner.calls[len(runner.calls)-1].args; !reflect.DeepEqual(last, []string{"workspace", "resume", "-s", "s-1", "--background", "--json"}) {
		t.Fatalf("argv=%v", last)
	}
}
