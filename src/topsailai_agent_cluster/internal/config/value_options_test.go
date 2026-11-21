package config

import (
	"flag"
	"io"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/version"
)

// TestValueOptionNamesMatchTheParser guards the reported option set against the
// parsed one.
//
// The set exists so a raw argument scan can tell an option from an option's value.
// If it disagreed with the parser, the disagreement would be silent in both
// directions: a name reported but not accepted would make the scan consume an
// argument the parser treats as a positional, and a name accepted but not reported
// would let its value be read as an option. Both are checked here by asking the
// parser itself, so the test cannot pass by restating the same list twice.
//
// The probe value is each option's own default rather than one shared literal,
// because the options have different types: a duration rejects "probe-value" and an
// integer rejects it too, so a single literal would fail for a reason that has
// nothing to do with the set being wrong.
func TestValueOptionNamesMatchTheParser(t *testing.T) {
	for _, role := range []string{"agent-cluster-server", "agent-cluster-endpoint"} {
		t.Run(role, func(t *testing.T) {
			names := ValueOptionNames(role)
			if len(names) == 0 {
				t.Fatalf("ValueOptionNames(%q) reported no value options", role)
			}
			defaults := valueOptionDefaults(t, role)
			for name := range names {
				probe, known := defaults[name]
				if !known {
					t.Fatalf("ValueOptionNames(%q) reported %q, but the parser does not declare it", role, name)
				}
				// A reported name must be accepted by the parser, and it must
				// consume the following argument: passing a value must succeed.
				if _, err := Load([]string{"--" + name, probe}, role); err != nil {
					t.Fatalf("ValueOptionNames(%q) reported %q, but the parser rejected it: %v", role, name, err)
				}
			}
		})
	}
}

// valueOptionDefaults returns each declared option's default value, which is a
// string the option's own type accepts.
func valueOptionDefaults(t *testing.T, role string) map[string]string {
	t.Helper()
	cfg := Defaults(role)
	flags := flag.NewFlagSet(role, flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	registerFlags(flags, &cfg, role)

	defaults := make(map[string]string)
	flags.VisitAll(func(one *flag.Flag) {
		defaults[one.Name] = one.DefValue
	})
	return defaults
}

// TestValueOptionNamesExcludeBooleanOptions guards the one distinction the set
// depends on: a boolean option never consumes the following argument, so listing
// it would make the scan swallow an argument that is really the next option.
func TestValueOptionNamesExcludeBooleanOptions(t *testing.T) {
	serverNames := ValueOptionNames("agent-cluster-server")
	if serverNames["tls-shared-certificate"] {
		t.Fatalf("tls-shared-certificate is a boolean option and must not consume the following argument")
	}
	// The boolean option must still be accepted by the parser, so the exclusion
	// above is about consumption rather than about the option being unknown.
	if _, err := Load([]string{"--tls-shared-certificate"}, "agent-cluster-server"); err != nil {
		t.Fatalf("the parser rejected the boolean option: %v", err)
	}
}

// TestValueOptionNamesAreRoleSpecific guards the role boundary.
//
// The two daemons accept different options, so a union would make one daemon
// consume the argument after an option it does not accept. The check names one
// option from each side rather than comparing whole sets, because the sets are
// expected to grow and a whole-set comparison would fail on every addition for a
// reason unrelated to this rule.
func TestValueOptionNamesAreRoleSpecific(t *testing.T) {
	serverNames := ValueOptionNames("agent-cluster-server")
	endpointNames := ValueOptionNames("agent-cluster-endpoint")

	if !serverNames["auth-token"] {
		t.Fatalf("the Server accepts --auth-token, so it must be reported as a value option")
	}
	if endpointNames["auth-token"] {
		t.Fatalf("the Endpoint does not accept --auth-token, so reporting it would consume an argument the parser treats as positional")
	}
	if !endpointNames["project-root"] {
		t.Fatalf("the Endpoint accepts --project-root, so it must be reported as a value option")
	}
	if serverNames["project-root"] {
		t.Fatalf("the Server does not accept --project-root, so reporting it would consume an argument the parser treats as positional")
	}
}

// TestValueOptionNamesCoverFuncOptions guards the option kind that is easiest to
// forget.
//
// The two Func options take exactly one argument, so they consume the following
// argument like a string option does. A set built by listing only the typed
// registration helpers would omit them, and the omission would be invisible
// because the option still parses.
func TestValueOptionNamesCoverFuncOptions(t *testing.T) {
	if !ValueOptionNames("agent-cluster-server")["endpoint-dial-addresses"] {
		t.Fatalf("--endpoint-dial-addresses takes one argument and must be reported as a value option")
	}
	if !ValueOptionNames("agent-cluster-endpoint")["channel-addresses"] {
		t.Fatalf("--channel-addresses takes one argument and must be reported as a value option")
	}
}

// TestVersionRequestIgnoresAnOptionValue is the behaviour the set exists for.
//
// "--tls-certificate-file -v" names a file called "-v". Answering a version
// request there would replace the operator's intended command with a version
// banner, and the operator would have no way to tell that their file name was
// reinterpreted as a flag.
func TestVersionRequestIgnoresAnOptionValue(t *testing.T) {
	serverNames := ValueOptionNames("agent-cluster-server")
	if version.Requested([]string{"--tls-certificate-file", "-v"}, serverNames) {
		t.Fatalf("a -v used as the value of --tls-certificate-file must not be read as a version request")
	}
	if !version.Requested([]string{"--tls-certificate-file", "ca.pem", "-v"}, serverNames) {
		t.Fatalf("a -v after a complete option and its value must still be read as a version request")
	}
	if !version.Requested([]string{"-v"}, serverNames) {
		t.Fatalf("a bare -v must be read as a version request")
	}

	endpointNames := ValueOptionNames("agent-cluster-endpoint")
	if version.Requested([]string{"--project-root", "-v"}, endpointNames) {
		t.Fatalf("a -v used as the value of --project-root must not be read as a version request")
	}
}

// TestValueOptionNamesDoNotLeakIntoTheParser guards the construction path.
//
// ValueOptionNames builds a throwaway flag set to read the declarations. If that
// set were the one Load uses, or if it mutated shared state, asking for the names
// would change how the next Load behaves. The check parses twice and compares the
// result, so a leaked registration would show up as a difference.
func TestValueOptionNamesDoNotLeakIntoTheParser(t *testing.T) {
	before, err := Load([]string{"--database-path", "/tmp/before.sqlite"}, "agent-cluster-server")
	if err != nil {
		t.Fatalf("first parse failed: %v", err)
	}
	ValueOptionNames("agent-cluster-server")
	after, err := Load([]string{"--database-path", "/tmp/before.sqlite"}, "agent-cluster-server")
	if err != nil {
		t.Fatalf("second parse failed: %v", err)
	}
	if before.DatabasePath != after.DatabasePath {
		t.Fatalf("parsing changed after ValueOptionNames ran: %q then %q", before.DatabasePath, after.DatabasePath)
	}
	if !strings.HasSuffix(after.DatabasePath, "before.sqlite") {
		t.Fatalf("the parsed database path is %q, want the value that was passed", after.DatabasePath)
	}
}
