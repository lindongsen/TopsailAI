// Configuration sources for the run subcommand.
//
// The Node reads its configuration from four places, and this file is the one
// place that decides which wins. Keeping the order in one function is the point:
// a precedence that is spread across the resolvers is a precedence nobody can
// state, and the value that wins becomes whatever the code happened to do first.
//
// The order is:
//
//	--set KEY=VALUE   >   environment variable   >   --env-file   >   compiled in
//
// The argument layer is the most specific statement an operator can make, because
// it is typed for this one launch. An environment variable is ambient: it is
// exported once and inherited by every process the shell starts. A file is a
// default for this installation. The compiled-in values are the fallback, and
// LoadConfig already prefers an environment value over them.
//
// A value that is generated in memory is not a source: it is what happens when
// none of the four supplies a node id or a credential, and it is handled by
// prepareStatelessIdentity rather than here.
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"topsailai_connector/internal/envfile"
)

// envFileVariable names the dotenv file to read.
//
// It follows CONNECTOR_CLI_ENV_FILE, so the two binaries spell the same concept
// the same way. A second spelling for one idea is a second thing to remember.
const envFileVariable = "CONNECTOR_NODE_ENV_FILE"

// overrideFlag collects repeated --set KEY=VALUE arguments.
//
// It is a flag.Value rather than a slice of strings so the flag package can
// accumulate it, and it is a map so a repeated key keeps its last value, which is
// what a shell does when the same variable is assigned twice.
type overrideFlag map[string]string

// String renders the collected pairs for the flag package's error messages.
//
// The values are not printed. A --set argument may carry a tunnel token, and a
// usage error that echoes it would write a secret to stderr, which is the one
// place the design forbids a secret from reaching.
func (o *overrideFlag) String() string {
	if o == nil || len(*o) == 0 {
		return ""
	}
	keys := make([]string, 0, len(*o))
	for key := range *o {
		keys = append(keys, key)
	}
	return strings.Join(keys, ",")
}

// Set records one KEY=VALUE pair.
//
// The key is validated as an environment variable name, because the pair is
// looked up by that name and a key that cannot be spelled as one would be a value
// nothing ever reads. The value is taken verbatim, including an `=`, so a secret
// containing one survives.
func (o *overrideFlag) Set(pair string) error {
	key, value, found := strings.Cut(pair, "=")
	if !found {
		return fmt.Errorf("--set %q has no =; want KEY=VALUE", pair)
	}
	if err := validateOverrideKey(key); err != nil {
		return err
	}
	if *o == nil {
		*o = make(overrideFlag, 1)
	}
	(*o)[key] = value
	return nil
}

// validateOverrideKey refuses a key that is not an environment variable name.
//
// The rule is the one envfile applies to a file: letters, digits and underscore,
// not starting with a digit. It is repeated rather than exported because the two
// callers report the failure differently, and a shared helper that returned a
// message would make one of them say the wrong thing about where the key came
// from.
func validateOverrideKey(key string) error {
	if key == "" {
		return fmt.Errorf("--set has an empty key; want KEY=VALUE")
	}
	for index, character := range key {
		switch {
		case character >= 'A' && character <= 'Z':
		case character >= 'a' && character <= 'z':
		case character == '_':
		case character >= '0' && character <= '9' && index > 0:
		default:
			return fmt.Errorf("--set key %q is not an environment variable name; want letters, digits and underscore, not starting with a digit", key)
		}
	}
	return nil
}

// validateOverrideArguments checks every --set pair before the flag package sees it.
//
// The flag package wraps a Set failure as `invalid value "<the whole argument>" for
// flag -set`, so a rejected pair is echoed verbatim to stderr. That is measured, not
// assumed: `--set BAD-KEY=super-secret-value` printed the secret. A --set argument may
// carry a tunnel token, and a usage error is the one place a secret must not reach, so
// the pair is validated here and the flag package only ever receives a valid one.
//
// The scan is a pre-pass rather than a replacement for the flag package: it recognises
// the four spellings the package accepts and leaves every other argument alone, so the
// flag package still decides what a flag is.
func validateOverrideArguments(arguments []string) error {
	for index := 0; index < len(arguments); index++ {
		argument := arguments[index]
		var pair string
		switch {
		case argument == "-set" || argument == "--set":
			if index+1 >= len(arguments) {
				return fmt.Errorf("--set needs a KEY=VALUE argument")
			}
			pair = arguments[index+1]
			index++
		case strings.HasPrefix(argument, "-set="):
			pair = strings.TrimPrefix(argument, "-set=")
		case strings.HasPrefix(argument, "--set="):
			pair = strings.TrimPrefix(argument, "--set=")
		default:
			continue
		}
		key, _, found := strings.Cut(pair, "=")
		if !found {
			return fmt.Errorf("--set has no =; want KEY=VALUE")
		}
		if err := validateOverrideKey(key); err != nil {
			return err
		}
	}
	return nil
}

// resolveEnvFile returns the dotenv file to read, or an empty string for none.
//
// The flag wins over the variable for the same reason the argument layer wins
// everywhere else: it is the more specific statement. A relative path is refused
// because it resolves differently per launch, which is the rule the six existing
// path variables already follow.
//
// There is deliberately no default location. The CLI looks beside its executable,
// because a caller runs it from anywhere and wants its configuration to follow it.
// A Node is started by a service manager, and a file that appeared in the working
// directory would silently change what an existing deployment serves. Reading only
// a file the operator named keeps the mode additive: a deployment that names no
// file behaves exactly as it did before this flag existed.
func resolveEnvFile(flagValue string, environment func(string) string) (string, error) {
	path := flagValue
	if path == "" {
		path = environment(envFileVariable)
	}
	if path == "" {
		return "", nil
	}
	if !filepath.IsAbs(path) {
		return "", fmt.Errorf("%s %q is relative; a relative path resolves differently per launch", envFileVariable, path)
	}
	return path, nil
}

// loadEnvFile reads the named file and refuses a path that does not exist.
//
// envfile.Load treats a missing file as an empty map, which is right for a default
// location: its absence must not stop the program. It is wrong for a file the
// operator named, because a typo would then silently fall through to the compiled-in
// values and the operator would believe a configuration is in force that was never
// read. The distinction is made here rather than in envfile, so the CLI keeps the
// behaviour it documents.
func loadEnvFile(path string) (map[string]string, error) {
	if path == "" {
		return nil, nil
	}
	values, err := envfile.Load(path)
	if err != nil {
		return nil, err
	}
	if values == nil {
		values = map[string]string{}
	}
	if len(values) == 0 {
		// An empty map is also what a missing file produces, so the file is probed
		// directly. A file that exists and holds only comments is a legitimate empty
		// configuration; a file that does not exist is a mistake worth reporting.
		if _, err := os.Stat(path); err != nil {
			return nil, fmt.Errorf("read %s: %w", path, err)
		}
	}
	return values, nil
}

// layeredLookup composes the four sources into the lookup LoadConfig expects.
//
// An empty value counts as unset at every layer, which is the rule the CLI already
// uses: a variable set to nothing is not a configuration. Without it, an exported
// but empty variable would shadow a file that does hold a value, and the operator
// would see a Node start with a value they did not write.
func layeredLookup(overrides map[string]string, environment func(string) string, file map[string]string) func(string) string {
	return func(key string) string {
		if value := overrides[key]; value != "" {
			return value
		}
		if value := environment(key); value != "" {
			return value
		}
		return file[key]
	}
}
