package main

import (
	"encoding/base64"
	"os"
	"path/filepath"
	"strings"
	"testing"

	"topsailai_connector/internal/node/embedded"
)

// statelessCommandEnvironment returns an environment that asks for stateless mode and
// names a config directory that does not exist yet.
//
// The directory is a child of a directory that does exist, so a creation attempt would
// succeed and be observable. A path whose parent is missing would fail for the wrong
// reason and prove nothing about the mode.
func statelessCommandEnvironment(t *testing.T) string {
	t.Helper()

	configDir := filepath.Join(t.TempDir(), "never-created")
	t.Setenv("CONNECTOR_NODE_SERVER_URL", "wss://127.0.0.1:8443/channel")
	t.Setenv("CONNECTOR_NODE_TUNNEL_TOKEN", "tunnel-token-of-sufficient-length")
	t.Setenv("CONNECTOR_NODE_CONFIG_DIR", configDir)
	t.Setenv("CONNECTOR_NODE_POLICY_FILE", "")
	t.Setenv("CONNECTOR_NODE_STATELESS", "1")
	return configDir
}

// setCommandEmbeddedPolicy installs an embedded policy document for one test and
// restores the previous value when the test ends.
func setCommandEmbeddedPolicy(t *testing.T, document string) {
	t.Helper()

	previous := embedded.PolicyBase64
	t.Cleanup(func() { embedded.PolicyBase64 = previous })

	if document == "" {
		embedded.PolicyBase64 = ""
		return
	}
	embedded.PolicyBase64 = base64.StdEncoding.EncodeToString([]byte(document))
}

// TestStatelessModeRefusesEveryFileBackedSubcommand checks that the five subcommands
// which read or rewrite the identity and credential files are refused in stateless mode.
//
// The refusal is the design decision, not a limitation: a command whose meaning depends
// on an environment variable is the hardest kind of defect to diagnose, because the same
// command would change the address of a file-backed Node and change nothing on a
// stateless one. Refusing is visible; silently redirecting to memory is not.
//
// The second assertion is the one that matters most. Each command is run against a config
// directory that does not exist, and the directory must still not exist afterwards. A
// refusal placed after ResolveConfigDir would have created the directory the mode exists
// to avoid, and the operator would see a correct error message next to a directory that
// should never have been written.
func TestStatelessModeRefusesEveryFileBackedSubcommand(t *testing.T) {
	cases := []struct {
		name      string
		arguments []string
	}{
		{"id", []string{"id"}},
		{"regenerate", []string{"regenerate"}},
		{"credential add", []string{"credential", "add", "--key-id", "caller"}},
		{"credential list", []string{"credential", "list"}},
		{"credential remove", []string{"credential", "remove", "--key-id", "caller"}},
	}

	for _, testCase := range cases {
		t.Run(testCase.name, func(t *testing.T) {
			configDir := statelessCommandEnvironment(t)

			err := run(testCase.arguments)
			if err == nil {
				t.Fatalf("run(%v) = nil error, want a refusal in stateless mode", testCase.arguments)
			}
			if !strings.Contains(err.Error(), "CONNECTOR_NODE_STATELESS=1") {
				t.Fatalf("run(%v) error = %q, want it to name CONNECTOR_NODE_STATELESS=1", testCase.arguments, err)
			}
			if !strings.Contains(err.Error(), "interactive console") {
				t.Fatalf("run(%v) error = %q, want it to name the way to change the value instead", testCase.arguments, err)
			}

			if _, statErr := os.Stat(configDir); !os.IsNotExist(statErr) {
				t.Fatalf("config directory %q exists after run(%v); the refusal must run before the directory is resolved, because resolving one creates it", configDir, testCase.arguments)
			}
		})
	}
}

// TestStatelessModeStillRunsTheNode checks that the refusal covers the file-backed
// subcommands and nothing else.
//
// A mode that refused `run` would be a mode that does nothing. This test starts the Node
// in stateless mode and requires it to reach the summary, which is the evidence that the
// refusal was scoped to the commands that write files rather than to the program.
func TestStatelessModeStillRunsTheNode(t *testing.T) {
	configDir := statelessCommandEnvironment(t)
	setCommandEmbeddedPolicy(t, "version: 1\nscopes: {}\ngrants: []\n")

	signals := make(chan os.Signal, 1)
	signals <- os.Interrupt

	var buffer strings.Builder
	if err := runNodeWithOutput(nil, signals, &buffer, false); err != nil {
		t.Fatalf("runNodeWithOutput() in stateless mode error = %v, want nil", err)
	}
	if !strings.Contains(buffer.String(), "=== connector-node ===") {
		t.Fatalf("stdout = %q, want the startup summary", buffer.String())
	}

	if _, statErr := os.Stat(configDir); !os.IsNotExist(statErr) {
		t.Fatalf("config directory %q exists after a stateless start; the mode must write nothing", configDir)
	}
}

// TestStatelessSummaryNamesTheModeInsteadOfTheFiles checks the two lines the summary
// replaces and the one sentence it adds.
//
// A stateless Node has no config directory and no credential file, so printing those two
// values would print two empty strings, which reads as a broken configuration rather than
// as a mode. The mode is named instead, together with the consequence the operator has to
// know: nothing survives a restart.
func TestStatelessSummaryNamesTheModeInsteadOfTheFiles(t *testing.T) {
	statelessCommandEnvironment(t)
	setCommandEmbeddedPolicy(t, "version: 1\nscopes: {}\ngrants: []\n")

	signals := make(chan os.Signal, 1)
	signals <- os.Interrupt

	var buffer strings.Builder
	if err := runNodeWithOutput(nil, signals, &buffer, false); err != nil {
		t.Fatalf("runNodeWithOutput() error = %v", err)
	}
	printed := buffer.String()

	if !strings.Contains(printed, "mode          : stateless") {
		t.Fatalf("stdout = %q, want a mode line naming stateless", printed)
	}
	if !strings.Contains(printed, "lost when this process exits") {
		t.Fatalf("stdout = %q, want the consequence of the mode: nothing survives a restart", printed)
	}
	if strings.Contains(printed, "config dir    :") {
		t.Fatalf("stdout = %q, want no config directory line, because there is no directory", printed)
	}
	if strings.Contains(printed, "credentials   :") {
		t.Fatalf("stdout = %q, want no credentials path line, because there is no file", printed)
	}
}

// TestStatelessSummaryPointsAtTheTerminalNotAFile checks the withheld-secret sentence.
//
// The file-backed form tells the operator to read the credentials file. A stateless Node
// has no such file, so that sentence would send them looking for something the mode
// exists to avoid creating. The stateless form names the terminal instead, which is the
// only place the secret can be seen.
func TestStatelessSummaryPointsAtTheTerminalNotAFile(t *testing.T) {
	statelessCommandEnvironment(t)
	setCommandEmbeddedPolicy(t, "version: 1\nscopes: {}\ngrants: []\n")

	signals := make(chan os.Signal, 1)
	signals <- os.Interrupt

	var buffer strings.Builder
	if err := runNodeWithOutput(nil, signals, &buffer, false); err != nil {
		t.Fatalf("runNodeWithOutput() error = %v", err)
	}
	printed := buffer.String()

	if !strings.Contains(printed, "because a stateless node writes no file") {
		t.Fatalf("stdout = %q, want the withheld notice to explain that a stateless node writes no file", printed)
	}
	if strings.Contains(printed, "read the credentials file named above") {
		t.Fatalf("stdout = %q, want no instruction to read a credentials file, because a stateless node has none", printed)
	}
	if !strings.Contains(printed, "withheld") {
		t.Fatalf("stdout = %q, want the secret withheld when stdout is not a terminal", printed)
	}
}

// TestStatelessSummaryPrintsTheSecretOnATerminal checks that the secret is still
// recoverable in stateless mode.
//
// A stateless Node writes no file, so the terminal is the only place the secret ever
// appears. A mode that withheld it everywhere would leave the operator with a Node that
// accepts a credential nobody can learn, which is a Node that refuses every caller.
func TestStatelessSummaryPrintsTheSecretOnATerminal(t *testing.T) {
	statelessCommandEnvironment(t)
	setCommandEmbeddedPolicy(t, "version: 1\nscopes: {}\ngrants: []\n")

	signals := make(chan os.Signal, 1)
	signals <- os.Interrupt

	var buffer strings.Builder
	if err := runNodeWithOutput(nil, signals, &buffer, true); err != nil {
		t.Fatalf("runNodeWithOutput() error = %v", err)
	}
	printed := buffer.String()

	if strings.Contains(printed, "withheld") {
		t.Fatalf("stdout = %q, want no withholding notice on a terminal", printed)
	}
	if !strings.Contains(printed, "key id        : ") {
		t.Fatalf("stdout = %q, want the key id, which is public", printed)
	}
	if !strings.Contains(printed, "credential    : ") {
		t.Fatalf("stdout = %q, want the copyable credential", printed)
	}
}

// TestStatelessModeRejectsAnUnknownValue checks that the switch is validated rather than
// read as a boolean.
//
// A security switch that silently accepts a spelling it does not understand is a switch
// whose state nobody can state. `true` is the spelling an operator is most likely to try,
// so it is the one that must be refused with a message naming the accepted values.
func TestStatelessModeRejectsAnUnknownValue(t *testing.T) {
	t.Setenv("CONNECTOR_NODE_STATELESS", "true")

	err := run([]string{"id"})
	if err == nil {
		t.Fatal("run(id) with CONNECTOR_NODE_STATELESS=true = nil error, want a refusal")
	}
	if !strings.Contains(err.Error(), "CONNECTOR_NODE_STATELESS") {
		t.Fatalf("error = %q, want it to name the variable", err)
	}
	if !strings.Contains(err.Error(), "1") || !strings.Contains(err.Error(), "0") {
		t.Fatalf("error = %q, want it to name the accepted values", err)
	}
}
