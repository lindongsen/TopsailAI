package main

import (
	"context"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

// The two provider stdout families a workspace row can name.
//
// The suffix is not decoration. It selects which file family the provider CLI
// reads, and it is part of the row's mapping key, so a row resolved from the
// wrong suffix would read a different file. The suffix is therefore recovered
// from the filename rather than assumed.
const (
	sessionStdoutSuffix = ".session.stdout"
	taskStdoutSuffix    = ".task.stdout"
)

// resolveTaskDir derives the provider task directory from the process
// environment, using the same precedence the provider CLI uses.
//
// The provider CLI resolves its home from TOPSAILAI_HOME, then HOME, then a fixed
// fallback, and reads stdout files from <home>/workspace/task. Repeating that
// rule here lets the Provider locate the same directory without asking the CLI.
// It is called once at startup and the result is passed down, so no later
// decision re-reads the environment.
func resolveTaskDir(environment []string) string {
	if configured := environmentValue(environment, "TOPSAILAI_HOME"); configured != "" {
		expanded := configured
		if strings.HasPrefix(expanded, "~") {
			if home := environmentValue(environment, "HOME"); home != "" {
				expanded = home + expanded[1:]
			}
		}
		if absolute, err := filepath.Abs(expanded); err == nil {
			return filepath.Join(absolute, "workspace", "task")
		}
	}
	if home := environmentValue(environment, "HOME"); home != "" {
		return filepath.Join(home, ".topsailai", "workspace", "task")
	}
	return filepath.Join("/topsailai", "workspace", "task")
}

// resolveRowTargetByDigest proves which workspace row a row-scoped key names by
// recomputing the key from the task directory's filenames.
//
// A row-scoped key is a digest over the row's own identity, and that identity is
// the session identifier, the filename and the task flag. All three are readable
// from a filename, so the row can be proven without running provider discovery.
// This is what keeps an output read from paying for a full workspace scan before
// the first byte.
//
// It reports false when the key is session-scoped, when no task directory is
// configured, or when the digest matches no file or more than one file. The
// caller then falls back to discovery, so an unprovable target is never guessed:
// a deleted file and an unknown key both end up refused by the same path that
// refused them before.
func (p *provider) resolveRowTargetByDigest(key string) (providerSessionTarget, bool) {
	if p.taskDir == "" || !strings.HasPrefix(key, sessionRowProviderKeyPrefix) {
		return providerSessionTarget{}, false
	}
	entries, err := os.ReadDir(p.taskDir)
	if err != nil {
		return providerSessionTarget{}, false
	}
	var proven *providerSessionTarget
	for _, entry := range entries {
		if entry.IsDir() {
			continue
		}
		sessionID, pid, isTask, ok := parseStdoutFilename(entry.Name())
		if !ok {
			continue
		}
		candidate, err := providerSessionKey(workspaceItem{
			SessionID: sessionID, ProviderRowKey: entry.Name(), IsTask: isTask,
		})
		if err != nil || candidate != key {
			continue
		}
		if proven != nil {
			// Two filenames cannot share one digest, so a second match means the
			// directory is inconsistent. Refuse rather than pick one.
			return providerSessionTarget{}, false
		}
		proven = &providerSessionTarget{
			SessionID: sessionID, ProviderRowKey: entry.Name(), PID: pid, IsTask: isTask,
		}
	}
	if proven == nil {
		return providerSessionTarget{}, false
	}
	return *proven, true
}

// parseStdoutFilename recovers the row identity a provider stdout filename
// encodes.
//
// The two families use different grammars, and the difference is load-bearing: a
// session stdout names its PID last, while a task stdout names it second and may
// carry further identifiers after it. Reading the wrong position would produce a
// PID belonging to a different process, so each family is parsed by its own rule.
func parseStdoutFilename(name string) (sessionID string, pid int64, isTask bool, ok bool) {
	switch {
	case strings.HasSuffix(name, taskStdoutSuffix):
		parts := strings.Split(strings.TrimSuffix(name, taskStdoutSuffix), ".")
		if len(parts) < 2 {
			return "", 0, false, false
		}
		parsed, err := strconv.ParseInt(parts[1], 10, 64)
		if err != nil || parsed <= 0 {
			return "", 0, false, false
		}
		return parts[0], parsed, true, true
	case strings.HasSuffix(name, sessionStdoutSuffix):
		parts := strings.Split(strings.TrimSuffix(name, sessionStdoutSuffix), ".")
		if len(parts) < 2 {
			return "", 0, false, false
		}
		parsed, err := strconv.ParseInt(parts[len(parts)-1], 10, 64)
		if err != nil || parsed <= 0 {
			return "", 0, false, false
		}
		return strings.Join(parts[:len(parts)-1], "."), parsed, false, true
	}
	return "", 0, false, false
}

// resolveReadTarget resolves one output read target, preferring the digest proof.
//
// A row-scoped key is proven from filenames when the task directory is readable,
// which avoids a full workspace discovery before the first byte. Every other case
// falls back to discovery: a session-scoped key can match several rows and needs
// the provider's own liveness selection, and a row whose file is gone cannot be
// proven at all. Falling back keeps one authority for the cases the shortcut
// cannot decide, so the shortcut can only remove work, never change an answer.
func (p *provider) resolveReadTarget(ctx context.Context, value *target) (providerSessionTarget, error) {
	key, err := validateSessionTarget(value)
	if err != nil {
		return providerSessionTarget{}, err
	}
	if proven, ok := p.resolveRowTargetByDigest(key); ok {
		return proven, nil
	}
	return p.resolveWorkspaceTarget(ctx, value)
}
