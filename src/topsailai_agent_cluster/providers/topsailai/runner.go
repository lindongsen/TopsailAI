package main

import (
	"bytes"
	"context"
	"fmt"
	"os"
	"os/exec"
	"path/filepath"
	"strings"
	"time"
)

const (
	executableEnvironment = "AGENT_CLUSTER_TOPSAILAI_EXECUTABLE"
	defaultExecutable     = "topsailai"
	defaultCommandTimeout = 30 * time.Second
)

// cliRunner executes the locally configured TopsailAI business CLI directly.
type cliRunner struct {
	executable  string
	environment []string
	timeout     time.Duration
}

// newCLIRunner loads immutable process configuration at Provider startup.
func newCLIRunner(environment []string) cliRunner {
	executable := environmentValue(environment, executableEnvironment)
	if executable == "" {
		executable = defaultExecutable
	}
	return cliRunner{
		executable:  executable,
		environment: providerEnvironment(executable, environment),
		timeout:     defaultCommandTimeout,
	}
}

// Run executes one fixed executable with an argv array and no shell.
func (r cliRunner) Run(parent context.Context, args []string, stdin []byte) ([]byte, []byte, error) {
	ctx, cancel := context.WithTimeout(parent, r.timeout)
	defer cancel()
	command := exec.CommandContext(ctx, r.executable, args...)
	command.Env = append([]string(nil), r.environment...)
	if stdin != nil {
		command.Stdin = bytes.NewReader(stdin)
	}
	var stdout bytes.Buffer
	var stderr bytes.Buffer
	command.Stdout = &stdout
	command.Stderr = &stderr
	err := command.Run()
	if ctx.Err() != nil {
		return stdout.Bytes(), stderr.Bytes(), ctx.Err()
	}
	if err != nil {
		return stdout.Bytes(), stderr.Bytes(), fmt.Errorf("run TopsailAI CLI: %w", err)
	}
	return stdout.Bytes(), stderr.Bytes(), nil
}

// providerEnvironment puts an absolute Provider executable directory first on PATH.
func providerEnvironment(executable string, base []string) []string {
	directory := filepath.Dir(executable)
	if !filepath.IsAbs(directory) || filepath.Dir(directory) == directory {
		return append([]string(nil), base...)
	}
	environment := make([]string, 0, len(base)+1)
	inherited := ""
	for _, entry := range base {
		if strings.HasPrefix(entry, "PATH=") {
			inherited = strings.TrimPrefix(entry, "PATH=")
			continue
		}
		environment = append(environment, entry)
	}
	return append(environment, "PATH="+prependPath(directory, inherited))
}

// prependPath puts directory first without duplicating an existing entry.
func prependPath(directory, inherited string) string {
	separator := string(os.PathListSeparator)
	for _, entry := range strings.Split(inherited, separator) {
		if entry == directory {
			return inherited
		}
	}
	if inherited == "" {
		return directory
	}
	return directory + separator + inherited
}

// environmentValue reads one exact environment entry.
func environmentValue(environment []string, key string) string {
	prefix := key + "="
	for _, entry := range environment {
		if strings.HasPrefix(entry, prefix) {
			return strings.TrimPrefix(entry, prefix)
		}
	}
	return ""
}
