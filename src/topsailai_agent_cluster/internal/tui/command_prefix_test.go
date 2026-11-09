package tui

import (
	"context"
	"strings"
	"testing"
)

// TestCommandPrefixIsOptionalOnCommandWord proves "/send" and "send" are the
// same command, including the admitted payload.
func TestCommandPrefixIsOptionalOnCommandWord(t *testing.T) {
	cases := []struct {
		name    string
		command string
	}{
		{name: "bare", command: "send hi"},
		{name: "prefixed", command: "/send hi"},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			stub := inputStub()
			input := "cd endpoint-1/session-1\n" + testCase.command + "\nquit\n"
			_, diagnostics := runInputScenario(t, stub, input, 8192)
			if diagnostics != "" {
				t.Fatalf("unexpected diagnostics=%q", diagnostics)
			}
			if stub.admit != 1 || len(stub.intents) != 1 {
				t.Fatalf("admissions=%d intents=%d", stub.admit, len(stub.intents))
			}
			if got, want := string(stub.intents[0].Payload), `{"text":"hi"}`; got != want {
				t.Fatalf("payload=%s want=%s", got, want)
			}
		})
	}
}

// TestCommandPrefixKeepsArgumentTextLiteral proves the prefix is stripped from
// the command word only, so a payload that starts with a slash is unchanged.
func TestCommandPrefixKeepsArgumentTextLiteral(t *testing.T) {
	stub := inputStub()
	_, diagnostics := runInputScenario(t, stub, "cd endpoint-1/session-1\nsend /help\nquit\n", 8192)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics=%q", diagnostics)
	}
	if len(stub.intents) != 1 {
		t.Fatalf("intents=%d", len(stub.intents))
	}
	if got, want := string(stub.intents[0].Payload), `{"text":"/help"}`; got != want {
		t.Fatalf("payload=%s want=%s", got, want)
	}
}

// TestCommandPrefixAcceptsAliasesAndHelp proves the prefix composes with the
// alias registry and with help target resolution.
func TestCommandPrefixAcceptsAliasesAndHelp(t *testing.T) {
	stub := inputStub()
	output, diagnostics := runInputScenario(t, stub, "/help\n/?\n/help /send\n/quit\n", 8192)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics=%q", diagnostics)
	}
	if !strings.Contains(output, "Current scope: workspace") {
		t.Fatalf("prefixed help did not render context help: %q", output)
	}
	if !strings.Contains(output, "Syntax: send [text]") {
		t.Fatalf("prefixed help target did not resolve: %q", output)
	}
}

// TestCommandPrefixQuitExits proves a prefixed control command still exits.
func TestCommandPrefixQuitExits(t *testing.T) {
	stub := inputStub()
	output, diagnostics := runInputScenario(t, stub, "/q\nlist\n", 8192)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics=%q", diagnostics)
	}
	if strings.Count(output, "workspace> ") != 1 {
		t.Fatalf("prefixed quit did not exit the REPL: %q", output)
	}
}

// TestBareSlashStaysUnknownCommand proves a lone "/" is rejected instead of
// being silently treated as an empty line.
func TestBareSlashStaysUnknownCommand(t *testing.T) {
	stub := inputStub()
	_, diagnostics := runInputScenario(t, stub, "/\nquit\n", 8192)
	assertActionableError(t, diagnostics, `error: unknown command "/" (try help)`)
}

// TestSlashRootNavigationIsUnchanged proves "cd /" still means the workspace
// root, so the command prefix never reinterprets an argument.
func TestSlashRootNavigationIsUnchanged(t *testing.T) {
	stub := scopeStub()
	output, diagnostics := runInputScenario(t, stub, "cd host-one\ncd /\nquit\n", 8192)
	if diagnostics != "" {
		t.Fatalf("unexpected diagnostics=%q", diagnostics)
	}
	if !strings.Contains(output, "endpoint[host-one/endpoint-1]>") {
		t.Fatalf("endpoint scope was not entered: %q", output)
	}
	if !strings.HasSuffix(strings.TrimSpace(output), "workspace>") {
		t.Fatalf("cd / did not return to workspace scope: %q", output)
	}
}

// TestCommandPrefixCompletionKeepsTypedPrefix proves Tab completes a prefixed
// command word without dropping the slash the operator typed.
func TestCommandPrefixCompletionKeepsTypedPrefix(t *testing.T) {
	cases := []struct {
		name   string
		prompt string
		typed  string
		want   string
	}{
		{name: "prefixed", prompt: "session[ai-dev/20261027152208]>", typed: "/se", want: "/send "},
		{name: "bare", prompt: "session[ai-dev/20261027152208]>", typed: "se", want: "send "},
	}
	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			var out strings.Builder
			editor := newLineEditor(8192, 100)
			for _, r := range testCase.typed {
				editor.insert(r)
			}
			terminal := &TerminalEditor{output: &out, editor: editor}
			if err := terminal.completeCommand(testCase.prompt); err != nil {
				t.Fatalf("completeCommand: %v", err)
			}
			if got := string(editor.text); got != testCase.want {
				t.Fatalf("completed text=%q want=%q", got, testCase.want)
			}
		})
	}
}

// TestHelpTargetAcceptsCommandPrefix pins help normalization for both entry points.
func TestHelpTargetAcceptsCommandPrefix(t *testing.T) {
	var prefixed, bare strings.Builder
	if err := PrintScopedCommandHelp(&prefixed, "/send", ScopeSession); err != nil {
		t.Fatalf("PrintScopedCommandHelp(/send): %v", err)
	}
	if err := PrintScopedCommandHelp(&bare, "send", ScopeSession); err != nil {
		t.Fatalf("PrintScopedCommandHelp(send): %v", err)
	}
	if prefixed.String() != bare.String() {
		t.Fatalf("prefixed help differs from bare help: %q vs %q", prefixed.String(), bare.String())
	}
	var overviewPrefixed, overviewBare strings.Builder
	if err := PrintCommandHelp(&overviewPrefixed, "/list"); err != nil {
		t.Fatalf("PrintCommandHelp(/list): %v", err)
	}
	if err := PrintCommandHelp(&overviewBare, "list"); err != nil {
		t.Fatalf("PrintCommandHelp(list): %v", err)
	}
	if overviewPrefixed.String() != overviewBare.String() {
		t.Fatalf("prefixed overview help differs from bare help")
	}
}

// TestCommandPrefixIsDocumented proves the operator can discover the prefix.
func TestCommandPrefixIsDocumented(t *testing.T) {
	var context strings.Builder
	if err := PrintScopedCommandHelp(&context, "", ScopeWorkspace); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(context.String(), commandPrefixHelp) {
		t.Fatalf("context help missing prefix note: %q", context.String())
	}
	var all strings.Builder
	if err := PrintScopedCommandHelp(&all, "all", ScopeWorkspace); err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(all.String(), commandPrefixHelp) {
		t.Fatalf("help all missing prefix note: %q", all.String())
	}
}

// TestCommandPrefixDoesNotAffectWizardAnswers proves the prefix is a REPL form
// only: a wizard answer that begins with a slash stays a literal answer.
func TestCommandPrefixDoesNotAffectWizardAnswers(t *testing.T) {
	state := interactiveState{}
	state.Scope = ScopeState{Kind: ScopeWorkspace}
	var out strings.Builder
	lines := make(chan lineReadResult, 1)
	lines <- lineReadResult{line: "/start"}
	value, err := launchAnswerValueOrControl(context.Background(), lines, &out, &out, &state, startFieldName(startFieldEndpoint), ColorPolicy{})
	if err != nil {
		t.Fatalf("launchAnswerValueOrControl: %v", err)
	}
	if value != "/start" {
		t.Fatalf("wizard answer=%q want literal /start", value)
	}
}
