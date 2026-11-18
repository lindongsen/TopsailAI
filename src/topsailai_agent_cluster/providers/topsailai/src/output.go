package main

import (
	"context"
	"encoding/json"
	"fmt"
	"strings"
)

const maxOutputBytes = 1 << 20

type outputPayload struct {
	MaxBytes int `json:"max_bytes"`
	MaxLines int `json:"max_lines"`
}

func (p *provider) readOutput(ctx context.Context, requested *target, raw json.RawMessage) (*outputSnapshot, error) {
	var payload outputPayload
	if err := decodeStrict(raw, &payload); err != nil || payload.MaxBytes < 0 || payload.MaxBytes > maxOutputBytes || payload.MaxLines < 0 || payload.MaxLines > 10000 {
		return nil, fmt.Errorf("%w: invalid output payload", errInvalidRequest)
	}
	resolved, err := p.resolveReadTarget(ctx, requested)
	if err != nil {
		return nil, err
	}
	lines := payload.MaxLines
	if lines == 0 {
		lines = 20
	}
	args := runtimeLogArgs(resolved, lines, false)
	var envelope struct {
		OK        bool   `json:"ok"`
		ErrorCode string `json:"error_code"`
		Response  *struct {
			Lines       []string `json:"lines"`
			Truncated   bool     `json:"truncated"`
			ScanLimited bool     `json:"scan_limited"`
		} `json:"response"`
	}
	if err := runJSON(ctx, p.runner, args, maxOutputBytes, &envelope); err != nil {
		return nil, err
	}
	if !envelope.OK || envelope.ErrorCode != "" || envelope.Response == nil || envelope.Response.Lines == nil {
		return nil, fmt.Errorf("runtime logs returned invalid response")
	}
	content := strings.Join(envelope.Response.Lines, "\n")
	truncated := envelope.Response.Truncated || envelope.Response.ScanLimited
	if payload.MaxBytes > 0 && len(content) > payload.MaxBytes {
		content = boundedString(content, payload.MaxBytes)
		truncated = true
	}
	return &outputSnapshot{ObservedAtMS: p.now().UnixMilli(), Content: content, Truncated: truncated, Complete: !truncated}, nil
}

func runtimeLogArgs(target providerSessionTarget, lines int, follow bool) []string {
	args := []string{"runtime", "logs", "-s", target.SessionID}
	if target.PID > 0 {
		args = append(args, "-p", fmt.Sprint(target.PID))
	}
	if target.IsTask {
		args = append(args, "--is-task")
	}
	args = append(args, "-n", fmt.Sprint(lines))
	if follow {
		return append(args, "--follow")
	}
	return append(args, "--json")
}
