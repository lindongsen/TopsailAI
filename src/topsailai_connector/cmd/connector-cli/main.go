// Command connector-cli calls one operation on a Connector Node through the Server.
//
// It is the same client the Server's `cli` subcommand runs, packaged as its own
// binary so a caller who only makes requests does not have to install the Server.
// The behaviour is identical because both entry points call the same package; only
// the program name in the messages and the configuration file location differ.
//
// Configuration is read from three places, and the first one that supplies a value
// wins:
//
//  1. a flag on the command line
//  2. an environment variable in the process environment
//  3. an environment variable in the configuration file
//
// The configuration file is `.env.local` in the directory that holds this
// executable, so a binary can be dropped into a directory with its settings and run
// from anywhere, including through a symlink on PATH. `CONNECTOR_CLI_ENV_FILE`
// names a different file instead.
package main

import (
	"fmt"
	"os"
	"path/filepath"

	"topsailai_connector/internal/envfile"
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
	program := programName(arguments)
	stderr := os.Stderr

	values, path, err := loadConfiguration()
	if err != nil {
		fmt.Fprintf(stderr, "%s: %v\n", program, err)
		return 2
	}
	warnAboutPermissions(program, path, stderr)

	// The process environment wins over the file, because a caller who exported a
	// value meant it for this one command, while the file is a default for this
	// installation. An empty value counts as unset, which is the same rule the flag
	// layer uses: a variable set to nothing is not a configuration.
	lookup := func(key string) string {
		if value := os.Getenv(key); value != "" {
			return value
		}
		return values[key]
	}

	return cli.RunAs(program, arguments[1:], lookup, os.Stdout, stderr)
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
func loadConfiguration() (map[string]string, string, error) {
	path, err := configurationPath()
	if err != nil {
		return nil, "", err
	}

	values, err := envfile.Load(path)
	if err != nil {
		return nil, path, fmt.Errorf("read %s: %w", path, err)
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
	if override := os.Getenv(cli.EnvEnvFile); override != "" {
		return override, nil
	}

	executable, err := os.Executable()
	if err != nil {
		return "", fmt.Errorf("locate this executable: %w", err)
	}
	return filepath.Join(filepath.Dir(executable), defaultConfigName), nil
}

// warnAboutPermissions reports a configuration file other accounts can read.
//
// It warns rather than refuses, because the file may legitimately be readable in a
// container where the only account is the one running the program, and a refusal
// there would stop a working installation. The warning names the file and the mode,
// so the reader can decide without being told what the mode means.
func warnAboutPermissions(program, path string, stderr *os.File) {
	info, err := os.Stat(path)
	if err != nil {
		return
	}
	if mode := info.Mode().Perm(); mode&0o077 != 0 {
		fmt.Fprintf(stderr, "%s: warning: %s is readable by other accounts (mode %04o); it holds credentials, so chmod 600 is recommended\n", program, path, mode)
	}
}
