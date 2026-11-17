package main

// The executor logs a policy refusal where the decision is made, and nothing in
// internal/endpoint proves that main wires the logger into the executor. The
// behavioural tests construct an Executor themselves and set Logger directly, so
// deleting the wiring line leaves every one of them green while a live Endpoint
// stops emitting the audit line.
//
// That gap was measured, not assumed: removing `executor.Logger = logger` from
// main.go kept all four policy refusal tests passing. A refusal that is durable
// in the journal but absent from the log is exactly the defect the logging was
// added to remove, so the wiring needs its own proof.
//
// The guard reads main.go instead of restating it, following the convention in
// catalog_deployment_guard_test.go and accesspolicy_warning_call_guard_test.go.
// It pins the ordering as well as the assignment: the logger must be wired before
// the PolicyHook that produces the refusal, because a hook installed on an
// executor with no logger refuses silently.

import (
	"strings"
	"testing"
)

// executorLoggerSource is the file that wires the logger into the executor.
const executorLoggerSource = "src/main/agent-cluster-endpoint/main.go"

// executorLoggerWiring is the assignment that gives the executor its logger.
const executorLoggerWiring = `executor.Logger = logger`

// executorPolicyHookInstall is the hook whose refusals the logger must report.
const executorPolicyHookInstall = `executor.PolicyHook = func(`

// TestExecutorLoggerIsWired pins that main.go gives the executor a logger, so a
// policy refusal decided by the command path reaches the log.
func TestExecutorLoggerIsWired(t *testing.T) {
	root := repoRoot(t)
	source := readRepoFile(t, root, executorLoggerSource)

	if !strings.Contains(source, executorLoggerWiring) {
		t.Fatalf("%s does not contain %q, so a policy refusal on the command path is recorded in the journal and never logged", executorLoggerSource, executorLoggerWiring)
	}
}

// TestExecutorLoggerIsWiredBeforeThePolicyHook pins the ordering: the logger must
// exist before the hook that logs through it is installed. Reversing the two
// leaves the hook in place and the log silent, which reads as a policy that
// refused nothing.
func TestExecutorLoggerIsWiredBeforeThePolicyHook(t *testing.T) {
	root := repoRoot(t)
	source := readRepoFile(t, root, executorLoggerSource)

	wiringIndex := strings.Index(source, executorLoggerWiring)
	if wiringIndex < 0 {
		t.Fatalf("%s does not contain %q", executorLoggerSource, executorLoggerWiring)
	}
	hookIndex := strings.Index(source, executorPolicyHookInstall)
	if hookIndex < 0 {
		t.Fatalf("%s does not contain %q", executorLoggerSource, executorPolicyHookInstall)
	}
	if hookIndex < wiringIndex {
		t.Fatalf("the policy hook is installed before the executor logger is wired in %s, so the hook refuses without logging", executorLoggerSource)
	}
}
