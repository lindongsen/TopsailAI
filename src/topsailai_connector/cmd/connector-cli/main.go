// Command connector-cli calls one operation on a Connector Node through the Server.
//
// It is the same client the Server's `cli` subcommand runs, packaged as its own
// binary so a caller who only makes requests does not have to install the Server.
// The behaviour is identical because both entry points call the same package; only
// the program name in the messages and the configuration file location differ.
//
// Configuration is read from four places, and the first one that supplies a value
// wins:
//
//  1. --set KEY=VALUE on the command line
//  2. an environment variable in the process environment
//  3. a KEY=VALUE pair in the configuration file
//  4. the built-in default, where one exists
//
// A dedicated flag such as --server is the same layer as --set and is read first,
// so --server wins over --set CONNECTOR_CLI_SERVER_URL.
//
// The configuration file is `.env.local` in the directory that holds this
// executable, so a binary can be dropped into a directory with its settings and run
// from anywhere, including through a symlink on PATH. `CONNECTOR_CLI_ENV_FILE`
// names a different file instead.
package main

import (
	"fmt"
	"io"
	"os"
	"path/filepath"

	"topsailai_connector/internal/server/cli"
)

// defaultConfigName is the configuration file looked for beside the executable.
const defaultConfigName = ".env.local"

func main() {
	os.Exit(run(os.Args))
}

// run is the whole process, separated from main so a test can call it and so every
// failure returns a status instead of calling os.Exit in the middle.
func run(arguments []string) int {
	return runWithOutput(arguments, os.Stdout, os.Stderr)
}

// runWithOutput is run with the two streams injected, so a test can read what the
// program printed instead of only its status.
//
// The status alone cannot prove a secret stayed out of the output: a program that
// echoes a credential and exits 2 has the right status and the wrong behaviour.
func runWithOutput(arguments []string, stdout, stderr io.Writer) int {
	program := programName(arguments)

	// The two configuration flags are extracted before anything else, because the
	// configuration has to be loaded before the operation is parsed: the operation's
	// own flags are resolved against the configuration, so a flag that changes the
	// configuration must be read first. The shared cli package never sees them, which
	// is why it does not have to know they exist.
	configuration, err := extractConfigurationArguments(arguments[1:])
	if err != nil {
		fmt.Fprintf(stderr, "%s: usage: %v\n", program, err)
		return 2
	}

	path, named, err := resolveConfigurationPath(configuration.envFile, os.Getenv)
	if err != nil {
		fmt.Fprintf(stderr, "%s: %v\n", program, err)
		return 2
	}
	values, err := loadConfigurationFile(path, named)
	if err != nil {
		fmt.Fprintf(stderr, "%s: %v\n", program, err)
		return 2
	}
	warnAboutPermissions(program, path, stderr)

	// The precedence is decided in one place, so the order is visible in one function
	// rather than scattered through the resolvers.
	lookup := layeredLookup(configuration.overrides, os.Getenv, values)

	return cli.RunAs(program, configuration.remaining, lookup, stdout, stderr)
}

// programName returns the name used as the prefix of every message.
//
// It is the executable's own base name rather than a constant, so a copy renamed by
// the operator reports the name the operator typed. A path with no base name falls
// back to a fixed string, because an empty prefix would print a message that looks
// like a continuation of the previous line.
func programName(arguments []string) string {
	if len(arguments) > 0 && arguments[0] != "" {
		if name := filepath.Base(arguments[0]); name != "." && name != string(filepath.Separator) {
			return name
		}
	}
	return "connector-cli"
}

// loadConfiguration reads the configuration file and reports where it looked.
//
// A missing file is not an error: the program then runs on the process environment
// alone, which is the ordinary case for a caller who exports the credentials. A file
// that exists and cannot be parsed is an error, because a configuration that is
// half-read is a configuration nobody can reason about.
//
// It is the no-flag form of the same work run does, kept as its own function because
// the tests exercise it directly and because a caller that names no file should not
// have to pass an empty flag value to say so.
func loadConfiguration() (map[string]string, string, error) {
	path, named, err := resolveConfigurationPath("", os.Getenv)
	if err != nil {
		return nil, "", err
	}
	values, err := loadConfigurationFile(path, named)
	if err != nil {
		return nil, path, err
	}
	return values, path, nil
}

// configurationPath returns the file to read.
//
// The default is beside the executable, resolved through os.Executable so a symlink
// on PATH still finds the real binary's directory. The override exists because a
// binary may live somewhere its configuration must not, such as a directory a build
// step deletes.
func configurationPath() (string, error) {
	path, _, err := resolveConfigurationPath("", os.Getenv)
	return path, err
}

// warnAboutPermissions reports a configuration file other accounts can read.
//
// It warns rather than refuses, because the file may legitimately be readable in a
// container where the only account is the one running the program, and a refusal
// there would stop a working installation. The warning names the file and the mode,
// so the reader can decide without being told what the mode means.
func warnAboutPermissions(program, path string, stderr io.Writer) {
	info, err := os.Stat(path)
	if err != nil {
		return
	}
	if mode := info.Mode().Perm(); mode&0o077 != 0 {
		fmt.Fprintf(stderr, "%s: warning: %s is readable by other accounts (mode %04o); it holds credentials, so chmod 600 is recommended\n", program, path, mode)
	}
}
