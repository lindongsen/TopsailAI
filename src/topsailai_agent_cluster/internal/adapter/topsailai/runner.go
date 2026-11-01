// Package topsailai provides the Endpoint-local TopsailAI adapter.
package topsailai

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
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
	if stdin != nil {
		cmd.Stdin = bytes.NewReader(stdin)
	}
	output, err := cmd.Output()
	if err != nil {
		if ctx.Err() != nil {
			return nil, ctx.Err()
		}
		return nil, fmt.Errorf("run TopsailAI command: %w", err)
	}
	return output, nil
}
