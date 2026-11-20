// Configuration sources for the CLI.
//
// The CLI reads its configuration from four places, and this file is the one place
// that decides which wins. Keeping the order in one function is the point: a
// precedence spread across the resolvers is a precedence nobody can state, and the
// value that wins becomes whatever the code happened to do first.
//
// The order is:
//
//	--set KEY=VALUE   >   environment variable   >   --env-file   >   the file
//
// The argument layer is the most specific statement a caller can make, because it is
// typed for this one command. An environment variable is ambient: it is exported once
// and inherited by every process the shell starts. A file is a default for this
// installation.
//
// The two flags are extracted here rather than registered in the shared cli package,
// because the configuration must be loaded before the operation is parsed: the
// operation's own flags are resolved against the configuration, so a flag that
// changes the configuration has to be read first. Extracting them also keeps the
// shared package unaware of a concern that belongs to this entry point.
package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"

	"topsailai_connector/internal/envfile"
)

// overrideFlag collects repeated --set KEY=VALUE arguments.
//
// It is a map so a repeated key keeps its last value, which is what a shell does when
// the same variable is assigned twice.
type overrideFlag map[string]string

// String renders the collected keys for the flag package's error messages.
//
// The values are not printed. A --set argument may carry a credential, and a usage
// error that echoed it would write a secret to stderr, which is the one place the
// design forbids a secret from reaching.
func (o overrideFlag) String() string {
	if len(o) == 0 {
		return ""
	}
	keys := make([]string, 0, len(o))
	for key := range o {
		keys = append(keys, key)
	}
	return strings.Join(keys, ",")
}

// set records one KEY=VALUE pair.
//
// The key is validated as an environment variable name, because the pair is looked up
// by that name and a key that cannot be spelled as one would be a value nothing ever
// reads. The value is taken verbatim, including an `=`, so a credential containing one
// survives.
func (o overrideFlag) set(pair string) error {
	key, value, found := strings.Cut(pair, "=")
	if !found {
		return fmt.Errorf("--set has no =; want KEY=VALUE")
	}
	if err := validateOverrideKey(key); err != nil {
		return err
	}
	o[key] = value
	return nil
}

// validateOverrideKey refuses a key that is not an environment variable name.
//
// The rule is the one envfile applies to a file: letters, digits and underscore, not
// starting with a digit. It is repeated rather than exported because the two callers
// report the failure differently, and a shared helper that returned a message would
// make one of them say the wrong thing about where the key came from.
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

// configurationArguments is the result of scanning the command line for the two
// configuration flags.
type configurationArguments struct {
	// remaining is the argument list with the two flags removed, so the shared cli
	// package never sees a flag it does not register.
	remaining []string
	// envFile is the value of --env-file, or empty when the flag was not given.
	envFile string
	// overrides holds the --set pairs.
	overrides overrideFlag
}

// extractConfigurationArguments removes --env-file and --set from the arguments.
//
// The scan recognises the four spellings Go's flag package accepts for each flag and
// leaves every other argument alone, so the package still decides what a flag is. A
// value that begins with `-` is refused rather than consumed, because an env-file path
// must be absolute and a `--set` pair must contain `=`: consuming the next flag as a
// value would turn a missing value into a confusing failure somewhere else.
//
// The pairs are validated here rather than by the flag package, because the package
// echoes a rejected value verbatim as `invalid value "<the whole argument>" for flag`.
// That is measured, not assumed: the Node printed a secret that way before the same
// pre-pass was added there.
func extractConfigurationArguments(arguments []string) (configurationArguments, error) {
	result := configurationArguments{overrides: overrideFlag{}}
	for index := 0; index < len(arguments); index++ {
		argument := arguments[index]
		switch {
		case argument == "-env-file" || argument == "--env-file":
			if index+1 >= len(arguments) || strings.HasPrefix(arguments[index+1], "-") {
				return configurationArguments{}, fmt.Errorf("--env-file needs a path")
			}
			result.envFile = arguments[index+1]
			index++
		case strings.HasPrefix(argument, "-env-file="):
			result.envFile = strings.TrimPrefix(argument, "-env-file=")
		case strings.HasPrefix(argument, "--env-file="):
			result.envFile = strings.TrimPrefix(argument, "--env-file=")
		case argument == "-set" || argument == "--set":
			if index+1 >= len(arguments) || strings.HasPrefix(arguments[index+1], "-") {
				return configurationArguments{}, fmt.Errorf("--set needs a KEY=VALUE argument")
			}
			if err := result.overrides.set(arguments[index+1]); err != nil {
				return configurationArguments{}, err
			}
			index++
		case strings.HasPrefix(argument, "-set="):
			if err := result.overrides.set(strings.TrimPrefix(argument, "-set=")); err != nil {
				return configurationArguments{}, err
			}
		case strings.HasPrefix(argument, "--set="):
			if err := result.overrides.set(strings.TrimPrefix(argument, "--set=")); err != nil {
				return configurationArguments{}, err
			}
		default:
			result.remaining = append(result.remaining, argument)
		}
	}
	return result, nil
}

// resolveConfigurationPath returns the file to read and whether the caller named it.
//
// The flag wins over the variable for the same reason the argument layer wins
// everywhere else: it is the more specific statement. A relative path is refused
// because it resolves differently per launch, which is the rule the six existing path
// variables already follow.
//
// The default is beside the executable, resolved through os.Executable so a symlink on
// PATH still finds the real binary's directory. That default is what makes a binary
// droppable into a directory with its settings.
func resolveConfigurationPath(flagValue string, environment func(string) string) (path string, named bool, err error) {
	if flagValue != "" {
		if !filepath.IsAbs(flagValue) {
			return "", false, fmt.Errorf("--env-file %q is relative; a relative path resolves differently per launch", flagValue)
		}
		return flagValue, true, nil
	}
	if override := environment("CONNECTOR_CLI_ENV_FILE"); override != "" {
		return override, false, nil
	}
	executable, err := os.Executable()
	if err != nil {
		return "", false, fmt.Errorf("locate this executable: %w", err)
	}
	return filepath.Join(filepath.Dir(executable), defaultConfigName), false, nil
}

// loadConfigurationFile reads the named file.
//
// A file the caller named with --env-file must exist, because a typo would otherwise
// silently fall through to the environment and the caller would believe a
// configuration is in force that was never read.
//
// A file named by CONNECTOR_CLI_ENV_FILE or found beside the executable is optional,
// and that difference is deliberate rather than an oversight. The variable predates
// the flag, and an installation whose variable points at a file that has since been
// deleted keeps working today; making it strict would remove a behaviour that is
// relied upon. The flag is new, so it can be strict from the start.
func loadConfigurationFile(path string, named bool) (map[string]string, error) {
	values, err := envfile.Load(path)
	if err != nil {
		return nil, fmt.Errorf("read %s: %w", path, err)
	}
	if named && len(values) == 0 {
		// envfile.Load reports a missing file as an empty map, so the absence has to be
		// probed separately. An empty map is also what a file holding only comments
		// produces, and that file exists, so the probe is a stat rather than a length
		// check.
		if _, statErr := os.Stat(path); statErr != nil {
			return nil, fmt.Errorf("read %s: %w", path, statErr)
		}
	}
	return values, nil
}

// layeredLookup composes the three sources into the lookup the cli package expects.
//
// The order is argument, then environment, then file. An empty value counts as unset
// at every layer, which is the rule the cli package already applies to its own flags:
// a variable set to nothing is not a configuration.
func layeredLookup(overrides overrideFlag, environment func(string) string, file map[string]string) func(string) string {
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
