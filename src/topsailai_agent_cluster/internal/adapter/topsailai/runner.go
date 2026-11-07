// Package topsailai provides the Endpoint-local TopsailAI adapter.
package topsailai

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

type commandRunner interface {
	Run(context.Context, string, []string, []byte) ([]byte, error)
}

type execRunner struct {
	timeout time.Duration
}

// Run executes the configured provider command with a bounded context.
func (r execRunner) Run(parent context.Context, executable string, args []string, stdin []byte) ([]byte, error) {
	ctx, cancel := context.WithTimeout(parent, r.timeout)
	defer cancel()
	cmd := exec.CommandContext(ctx, executable, args...)
	cmd.Env = providerEnvironment(executable, os.Environ())
	if stdin != nil {
		cmd.Stdin = bytes.NewReader(stdin)
	}
	output, err := cmd.Output()
	if err != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		// The provider reports a rejected, failed or unconfirmed outcome as a
		// structured document on stdout with a non-zero exit code, so the captured
		// document must survive the failure instead of being discarded. Callers that
		// treat any error as a plain failure still ignore it.
		return output, fmt.Errorf("run TopsailAI command: %w", err)
	}
	return output, nil
}

// providerEnvironment returns base with the provider executable's own directory
// first on PATH.
//
// The provider CLI spawns sibling executables by bare name (for example
// topsailai_launch_agent), so it resolves them through the inherited PATH. A
// daemon started by a service manager does not inherit the operator's shell
// PATH, so the provider directory must be added explicitly; otherwise the
// provider fails with spawn_failed even though its own argv is correct.
func providerEnvironment(executable string, base []string) []string {
	directory := filepath.Dir(executable)
	// A relative executable has no trustworthy directory, and a provider
	// installed at the filesystem root would put "/" on PATH, which resolves
	// every bare name. Leave the inherited environment untouched in both cases.
	if !filepath.IsAbs(directory) || filepath.Dir(directory) == directory {
		return base
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

// prependPath puts directory first unless it is already present, so a repeated
// execution never grows PATH with duplicate entries.
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
