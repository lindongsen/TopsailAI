package bdd

import (
	"fmt"
	"strings"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/tests/harness"
)

// registerMessagesSteps registers the provider conversation rendering scenarios.
//
// These scenarios exist because the rendering, the display bound and the bound
// refusals are only observable in the terminal an operator runs. A unit test
// proves the renderer and the flag parser separately; only this layer proves the
// shipped binary wires them together, which is exactly the gap that let a stale
// binary report zero counts while every unit test passed.
func registerMessagesSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^a real cluster with a session holding a structured body$`, startMessagesCluster)
	ctx.Step(`^the messages command is run for that session$`, runMessages)
	ctx.Step(`^every message is rendered as a separated block with a header$`, assertMessagesBlocks)
	ctx.Step(`^the reported counts are real measurements$`, assertMessagesCounts)
	ctx.Step(`^the body shows the step label and its text without the record keys$`, assertMessagesUnwrapped)
	ctx.Step(`^the messages command is run with a character bound$`, runMessagesWithBound)
	ctx.Step(`^the messages command is run with a token bound$`, runMessagesTokenBound)
	ctx.Step(`^the body is shortened and the header counts are unchanged$`, assertMessagesBounded)
	ctx.Step(`^the messages command is run with a bound above the maximum$`, runMessagesAboveMaximum)
	ctx.Step(`^the command is refused and names the maximum$`, assertMessagesMaximumRefused)
	ctx.Step(`^the messages command is run with a negative bound$`, runMessagesNegativeBound)
	ctx.Step(`^the command is refused and names the value as negative$`, assertMessagesNegativeRefused)
	ctx.Step(`^the messages command is run with two disagreeing spellings$`, runMessagesDisagreeingSpellings)
	ctx.Step(`^the command is refused and asks for one bound$`, assertMessagesDisagreementRefused)
}

// messagesFixtureSession is the provider session key the fixture records. The
// command takes the provider session identifier, not the opaque cluster resource
// identifier, because the Server forwards it verbatim as the provider selector.
const messagesFixtureSession = "fixture-session"

// messagesStepRecord is a real provider step record, not prose.
//
// The body must be a record carrying a step name and raw text, because that is
// the shape the adapter unwraps. A plain prose body would make the unwrapping
// scenario pass while proving nothing: the adapter returns a non-record body
// unchanged, so the assertion could not distinguish "unwrapped" from "never
// needed unwrapping".
const messagesStepRecord = `{"step_name":"task","raw_text":"the operator wrote this"}`

// messagesStepLabel is the label the adapter emits for the step record above. It
// is the provider's own prefix followed by the step name.
const messagesStepLabel = "topsailai.task"

// messagesStepText is the operator text carried inside the record.
const messagesStepText = "the operator wrote this"

// messagesRule is the separator drawn above and below every header. Asserting it
// proves the block structure exists rather than only the header text.
var messagesRule = strings.Repeat("=", 80)

// startMessagesCluster starts a real cluster whose fixture records a structured
// body. The body is delivered through the fault-injection seam because that is
// the only channel that reaches the Endpoint process, and the fixture runs as its
// child.
func startMessagesCluster() error {
	if activeTest == nil {
		return fmt.Errorf("active BDD test is not initialized")
	}
	if activeScenario.world == nil {
		activeScenario.world = &World{}
	}
	cluster, err := harness.StartCluster(activeTest, harness.ClusterOptions{
		ProviderType: "topsailai",
		Faults: harness.FaultInjection{
			MessagesBody:  messagesStepRecord,
			MessagesCount: 2,
		},
	})
	if err != nil {
		return err
	}
	activeScenario.world.realCluster = cluster
	activeScenario.realCluster = cluster
	if _, err := cluster.BuildTUI(activeTest); err != nil {
		return fmt.Errorf("build CLI: %w", err)
	}
	return nil
}

// runMessages runs the plain command and records its result without judging it.
func runMessages() error {
	return runMessagesCommand()
}

// runMessagesWithBound runs the same command with a short character bound.
func runMessagesWithBound() error {
	return runMessagesCommand("-c", "20")
}

// runMessagesTokenBound runs the same command with a short token bound.
//
// The bound is 3 because the unwrapped body is about ten cl100k_base tokens: small
// enough to shorten it, large enough to leave a readable prefix. A bound of 200 would
// not shorten anything, which is the vacuous pass that had to be fixed once already in
// the renderer tests.
func runMessagesTokenBound() error {
	return runMessagesCommand("-t", "3")
}

// runMessagesAboveMaximum runs the command with a bound above the protocol limit.
func runMessagesAboveMaximum() error {
	return runMessagesCommand("--max-chars", "100001")
}

// runMessagesNegativeBound runs the command with a negative bound.
func runMessagesNegativeBound() error {
	return runMessagesCommand("--max-chars", "-5")
}

// runMessagesDisagreeingSpellings runs the command with both spellings set to
// different values, which must be refused rather than resolved by precedence.
func runMessagesDisagreeingSpellings() error {
	return runMessagesCommand("--max-chars", "40", "-c", "50")
}

// runMessagesCommand runs one messages invocation and records its output.
//
// A non-zero exit status is recorded rather than treated as a step failure,
// because the refusal scenarios expect one. Only a launch failure is reported
// here, so a broken binary cannot be mistaken for a correct refusal.
func runMessagesCommand(extra ...string) error {
	if activeScenario.realCluster == nil {
		return fmt.Errorf("real cluster is not running")
	}
	args := append([]string{"messages", "endpoint-1", messagesFixtureSession}, extra...)
	stdout, stderr, code, runErr := activeScenario.realCluster.RunTUI(args...)
	activeScenario.lastBody = []byte(stdout + stderr)
	activeScenario.lastStatus = code
	if runErr != nil && code == 0 {
		return fmt.Errorf("run messages: %v stderr=%s", runErr, stderr)
	}
	return nil
}

// assertMessagesBlocks proves each message is a separated block with a header.
func assertMessagesBlocks() error {
	if activeScenario.lastStatus != 0 {
		return fmt.Errorf("messages failed with exit code=%d output=%s", activeScenario.lastStatus, interactiveOutput())
	}
	text := interactiveOutput()
	if !strings.Contains(text, messagesRule) {
		return fmt.Errorf("no block separator was rendered, so the conversation is not shown as blocks: %s", text)
	}
	for _, header := range []string{"#1 - Role:", "#2 - Role:"} {
		if !strings.Contains(text, header) {
			return fmt.Errorf("message header %q is missing: %s", header, text)
		}
	}
	return nil
}

// assertMessagesCounts proves the counts are measurements rather than the zero
// placeholder a stale or unwired binary reports.
func assertMessagesCounts() error {
	text := interactiveOutput()
	if strings.Contains(text, "Words: 0 - Tokens: 0") {
		return fmt.Errorf("the counts are the zero placeholder, so the binary does not measure the body: %s", text)
	}
	if !strings.Contains(text, "Words: ") || !strings.Contains(text, " - Tokens: ") {
		return fmt.Errorf("the header does not report word and token counts: %s", text)
	}
	return nil
}

// assertMessagesUnwrapped proves the step record was unwrapped in the adapter.
//
// The record keys must be absent as whole tokens, because a substring match on a
// short key can be satisfied by unrelated text. The step label and the operator
// text must both be present, so the assertion cannot pass on a body that was
// merely dropped.
func assertMessagesUnwrapped() error {
	text := interactiveOutput()
	if !strings.Contains(text, messagesStepLabel) {
		return fmt.Errorf("the step label %q is missing, so the record was not unwrapped: %s", messagesStepLabel, text)
	}
	if !strings.Contains(text, messagesStepText) {
		return fmt.Errorf("the operator text is missing, so unwrapping lost the body: %s", text)
	}
	for _, key := range []string{"raw_text", "step_name"} {
		if containsToken(text, key) {
			return fmt.Errorf("the record key %q reached the terminal, so the body was printed as JSON: %s", key, text)
		}
	}
	return nil
}

// assertMessagesBounded proves the bound shortened the body while the header
// counts still describe the full stored body.
//
// The counts are measured before truncation, so a shortened body must not change
// them. Asserting both halves is what stops the scenario from passing on a bound
// that was ignored or on counts that were recomputed from the shortened text.
func assertMessagesBounded() error {
	if activeScenario.lastStatus != 0 {
		return fmt.Errorf("messages with a bound failed with exit code=%d output=%s", activeScenario.lastStatus, interactiveOutput())
	}
	text := interactiveOutput()
	if !strings.Contains(text, "...") {
		return fmt.Errorf("the body was not shortened, so the bound was ignored: %s", text)
	}
	if strings.Contains(text, messagesStepText) {
		return fmt.Errorf("the full body is still present, so the bound did not apply: %s", text)
	}
	if strings.Contains(text, "Words: 0 - Tokens: 0") {
		return fmt.Errorf("the counts became the zero placeholder after truncation: %s", text)
	}
	if count := strings.Count(text, "shortened to the requested bound"); count != 1 {
		return fmt.Errorf("the truncation label appeared %d times, want exactly 1: %s", count, text)
	}
	return nil
}

// assertMessagesMaximumRefused proves a bound above the protocol maximum is
// refused instead of silently clamped.
func assertMessagesMaximumRefused() error {
	if activeScenario.lastStatus == 0 {
		return fmt.Errorf("a bound above the maximum was accepted, so it was silently clamped: %s", interactiveOutput())
	}
	text := interactiveOutput()
	if !strings.Contains(text, "exceeds the maximum of 100000") {
		return fmt.Errorf("the refusal does not name the maximum: %s", text)
	}
	return nil
}

// assertMessagesNegativeRefused proves a negative bound is refused instead of
// being read as "no bound", which would render the whole conversation.
func assertMessagesNegativeRefused() error {
	if activeScenario.lastStatus == 0 {
		return fmt.Errorf("a negative bound was accepted, so it was read as no bound: %s", interactiveOutput())
	}
	text := interactiveOutput()
	if !strings.Contains(text, "is negative") {
		return fmt.Errorf("the refusal does not name the value as negative: %s", text)
	}
	return nil
}

// assertMessagesDisagreementRefused proves two disagreeing spellings are refused
// rather than resolved by precedence, because either choice would silently ignore
// a bound the operator stated.
func assertMessagesDisagreementRefused() error {
	if activeScenario.lastStatus == 0 {
		return fmt.Errorf("two disagreeing spellings were accepted, so one bound was silently ignored: %s", interactiveOutput())
	}
	text := interactiveOutput()
	if !strings.Contains(text, "disagree") {
		return fmt.Errorf("the refusal does not report the disagreement: %s", text)
	}
	return nil
}

// containsToken reports whether a token appears as a whole word.
//
// A substring match is not an identity match: a short key can appear inside an
// unrelated word, so the text is split on the characters that cannot be part of a
// key and each piece is compared exactly.
func containsToken(text, token string) bool {
	for _, field := range strings.FieldsFunc(text, func(r rune) bool {
		switch r {
		case ' ', '\t', '\n', '\r', '"', '\'', ':', ',', '{', '}', '[', ']', '(', ')', '=', '-', '.', '/', '\\':
			return true
		}
		return false
	}) {
		if field == token {
			return true
		}
	}
	return false
}
