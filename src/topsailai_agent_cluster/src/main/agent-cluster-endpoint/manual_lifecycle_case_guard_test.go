package main

// The lifecycle manual cases tell a tester what the CLI prints after a mutation:
// the automatic tail announcement, the scope-recovery notices, the automatic-step
// diagnostics, the interrupt default, the empty task answer and the confirmation
// prompts. Each of those is a claim about a string the CLI builds, so each is
// checked against the function that builds it rather than against a copy of the
// wording. A tester who waits for a line the CLI never writes reports a defect
// that is not there, and a tester who answers a prompt expecting the other
// default records a FAIL for correct behaviour.

import (
	"strings"
	"testing"
)

// lifecycleDocumentPath is the manual case file these guards read.
const lifecycleDocumentPath = "tests/manual/live-tmux/lifecycle.md"

// lifecycleDocument reads the manual case file and refuses to continue on an
// empty document, because every assertion below would then pass vacuously.
func lifecycleDocument(t *testing.T) string {
	t.Helper()
	document := readRepoFile(t, repoRoot(t), lifecycleDocumentPath)
	if strings.TrimSpace(document) == "" {
		t.Fatalf("%s is empty, so this guard checked nothing", lifecycleDocumentPath)
	}
	return document
}

// lifecycleParagraph returns the line number and text of the paragraph that
// carries an anchor phrase. It names the lifecycle document in its failure
// message, because the shared paragraph helper names the navigation document and
// would blame the wrong file when reused here.
func lifecycleParagraph(t *testing.T, document, anchor string) (int, string) {
	t.Helper()
	offset := 0
	for _, paragraph := range strings.Split(document, "\n\n") {
		if index := strings.Index(paragraph, anchor); index >= 0 {
			return lineAt(document, offset+index), paragraph
		}
		offset += len(paragraph) + 2
	}
	t.Fatalf("%s holds no paragraph containing %q, so this guard checked nothing", lifecycleDocumentPath, anchor)
	return 0, ""
}

// TestLifecycleDocumentStatesTheFollowAnnouncement pins the automatic tail
// announcement. armFollowStream prints the shared follow prefix followed by the
// session ID and the stop hint, and it drops the redundant "follow: " word on
// purpose, so a document that still quotes "follow: <session-id>" sends the
// tester looking for a line that never appears.
func TestLifecycleDocumentStatesTheFollowAnnouncement(t *testing.T) {
	root := repoRoot(t)
	document := lifecycleDocument(t)
	follow := parseRepoGoFile(t, root, "internal/tui/follow.go")
	prefix, ok := stringConsts(follow)["followStatusPrefix"]
	if !ok || prefix == "" {
		t.Fatalf("internal/tui/follow.go declares no followStatusPrefix, so this guard cannot know the announcement prefix")
	}
	arm := functionSource(t, root, "internal/tui/interactive_ops.go", "armFollowStream")
	if !strings.Contains(arm, `" (any key stops)"`) {
		t.Fatalf("armFollowStream no longer announces the tail with (any key stops), so this guard is checking a stale shape")
	}
	want := prefix + "<session-id> (any key stops)"
	if !strings.Contains(document, want) {
		t.Fatalf("%s does not state the automatic tail announcement as %s, which is what armFollowStream prints, so a tester waits for a line the CLI never writes", lifecycleDocumentPath, want)
	}
	if strings.Contains(document, "`follow: <session-id>") {
		t.Fatalf("%s still states the announcement as follow: <session-id>, but the prefix is %s and armFollowStream drops the redundant follow: word", lifecycleDocumentPath, prefix)
	}
}

// TestLifecycleDocumentStatesTheScopeRecoveryNotices pins both notices that
// reconcileStoppedSelection prints. The unchanged notice carries the session
// identity in front of the quoted text, so a document that quotes only the tail
// understates what the operator sees.
func TestLifecycleDocumentStatesTheScopeRecoveryNotices(t *testing.T) {
	root := repoRoot(t)
	document := lifecycleDocument(t)
	reconcile := functionSource(t, root, "internal/tui/interactive_ops.go", "reconcileStoppedSelection")
	const removed = "is no longer reported by endpoint %s; returned to endpoint scope"
	const unchanged = "scope unchanged: endpoint inventory unavailable; use cd .. to leave the session scope"
	for _, needle := range []string{removed, unchanged} {
		if !strings.Contains(reconcile, needle) {
			t.Fatalf("reconcileStoppedSelection no longer prints %q, so this guard is checking a stale message", needle)
		}
	}
	if !strings.Contains(reconcile, "session %s "+unchanged) {
		t.Fatalf("reconcileStoppedSelection no longer prefixes the unchanged notice with the session identity, so the document would overstate what the CLI prints")
	}
	if !strings.Contains(document, "is no longer reported by endpoint <endpoint-id>; returned to endpoint scope") {
		t.Fatalf("%s does not state the removed-session notice, which is what reconcileStoppedSelection prints", lifecycleDocumentPath)
	}
	if !strings.Contains(document, "session <identity> "+unchanged) {
		t.Fatalf("%s does not state the unchanged notice with the session identity in front, which is what reconcileStoppedSelection prints", lifecycleDocumentPath)
	}
}

// TestLifecycleDocumentStatesTheAutomaticDiagnostics pins the three automatic
// step diagnostics. writeAutomaticDiagnostic joins the failure prefix and the
// detail with a semicolon, so the documented lines are the joined form.
func TestLifecycleDocumentStatesTheAutomaticDiagnostics(t *testing.T) {
	root := repoRoot(t)
	document := lifecycleDocument(t)
	write := functionSource(t, root, "internal/tui/navigation.go", "writeAutomaticDiagnostic")
	if !strings.Contains(write, `"%s; %s\n"`) {
		t.Fatalf("writeAutomaticDiagnostic no longer joins the prefix and the detail with a semicolon, so the documented diagnostics are stale")
	}
	auto := functionSource(t, root, "internal/tui/interactive_ops.go", "autoFollowAfterAction")
	for _, needle := range []string{"automatic follow failed: ", "automatic follow unavailable: "} {
		if !strings.Contains(auto, needle) {
			t.Fatalf("autoFollowAfterAction no longer reports %q, so this guard is checking a stale diagnostic", needle)
		}
	}
	refresh := functionSource(t, root, "internal/tui/navigation.go", "refreshSelectedSession")
	if !strings.Contains(refresh, "automatic refresh failed: ") {
		t.Fatalf("refreshSelectedSession no longer reports automatic refresh failed, so this guard is checking a stale diagnostic")
	}
	for _, needle := range []string{
		"send completed; automatic follow failed:",
		"send completed; automatic refresh failed:",
		"send completed; automatic follow unavailable:",
	} {
		if !strings.Contains(document, needle) {
			t.Fatalf("%s does not state %q, which is a diagnostic the CLI prints after an accepted send", lifecycleDocumentPath, needle)
		}
	}
}

// TestLifecycleDocumentStatesTheInterruptDefault pins the guided interrupt
// default. promptInterruptPayload selects hard for an empty answer and says so in
// its question, so a document that says an empty answer selects soft makes a
// tester record a FAIL for correct behaviour.
func TestLifecycleDocumentStatesTheInterruptDefault(t *testing.T) {
	root := repoRoot(t)
	document := lifecycleDocument(t)
	guided := functionSource(t, root, "internal/tui/interactive_ops.go", "promptInterruptPayload")
	if !strings.Contains(guided, `action = "hard"`) {
		t.Fatalf("promptInterruptPayload no longer selects hard for an empty answer, so the documented default is stale")
	}
	if !strings.Contains(guided, "empty selects hard") {
		t.Fatalf("promptInterruptPayload no longer advertises the default in its question, so the documented question is stale")
	}
	line, paragraph := lifecycleParagraph(t, document, "guided form")
	if !strings.Contains(paragraph, "empty answer selects") || !strings.Contains(paragraph, "hard") {
		t.Fatalf("%s:%d does not state that an empty answer selects hard, which is what promptInterruptPayload does", lifecycleDocumentPath, line)
	}
	if strings.Contains(paragraph, "empty answer selects soft") {
		t.Fatalf("%s:%d states that an empty answer selects soft, but promptInterruptPayload selects hard", lifecycleDocumentPath, line)
	}
}

// TestLifecycleDocumentStatesTheEmptyTaskAnswer pins the empty task answer. An
// empty answer at start.task> enters multi-line task mode rather than cancelling,
// and an empty block is rejected with its own message, so a document that groups
// empty input with cancel makes a tester expect a cancellation that never comes.
func TestLifecycleDocumentStatesTheEmptyTaskAnswer(t *testing.T) {
	root := repoRoot(t)
	document := lifecycleDocument(t)
	task := functionSource(t, root, "internal/tui/launch.go", "launchTaskAnswer")
	if !strings.Contains(task, "launchMultiLineTask") {
		t.Fatalf("launchTaskAnswer no longer enters multi-line task mode on an empty answer, so the documented behaviour is stale")
	}
	const empty = "task must not be empty; enter a task or cancel"
	multi := functionSource(t, root, "internal/tui/launch.go", "launchMultiLineTask")
	if !strings.Contains(multi, empty) {
		t.Fatalf("launchMultiLineTask no longer rejects an empty block with %q, so this guard is checking a stale message", empty)
	}
	line, paragraph := lifecycleParagraph(t, document, "multi-line task mode")
	if !strings.Contains(paragraph, empty) {
		t.Fatalf("%s:%d states multi-line task mode without the empty-block rejection %q, so a tester cannot tell what an empty block does", lifecycleDocumentPath, line, empty)
	}
	if !strings.Contains(paragraph, "start cancelled") {
		t.Fatalf("%s:%d no longer states that cancel prints start cancelled, which is what launchTaskAnswer does", lifecycleDocumentPath, line)
	}
}

// TestLifecycleDocumentStatesTheCommandBudget pins the interactive command
// budget the timing case waits against. The case tells the tester to wait longer
// than the budget, so a stale number makes the case wait the wrong amount.
func TestLifecycleDocumentStatesTheCommandBudget(t *testing.T) {
	root := repoRoot(t)
	document := lifecycleDocument(t)
	const budget = "defaultWaitTimeout = 10 * time.Second"
	actions := readRepoFile(t, root, "internal/tui/actions.go")
	if !strings.Contains(actions, budget) {
		t.Fatalf("internal/tui/actions.go no longer declares %q, so the documented budget is stale", budget)
	}
	line, paragraph := lifecycleParagraph(t, document, "command budget")
	if !strings.Contains(paragraph, "10 s") {
		t.Fatalf("%s:%d does not state the 10 s command budget, which is what defaultWaitTimeout sets", lifecycleDocumentPath, line)
	}
}

// TestLifecycleDocumentStatesTheConfirmationPrompts pins the two prompts the
// cases tell the tester to read. Both are built from constants, so the document
// must quote the assembled form rather than a paraphrase.
func TestLifecycleDocumentStatesTheConfirmationPrompts(t *testing.T) {
	root := repoRoot(t)
	document := lifecycleDocument(t)
	style := readRepoFile(t, root, "internal/tui/style.go")
	const hint = `confirmationHint = "[y/N]"`
	if !strings.Contains(style, hint) {
		t.Fatalf("internal/tui/style.go no longer declares %q, so the documented hint is stale", hint)
	}
	if !strings.Contains(style, `sendConfirmPrompt = "send.confirm" + confirmationHint + "> "`) {
		t.Fatalf("style.go no longer builds sendConfirmPrompt from send.confirm and confirmationHint, so the documented prompt is stale")
	}
	if !strings.Contains(style, `answerPrompt = "answer> "`) {
		t.Fatalf("style.go no longer declares answerPrompt as answer>, so the documented prompt is stale")
	}
	for _, needle := range []string{"send.confirm[y/N]>", "answer>"} {
		if !strings.Contains(document, needle) {
			t.Fatalf("%s does not name %q, which is a prompt the CLI prints", lifecycleDocumentPath, needle)
		}
	}
}
