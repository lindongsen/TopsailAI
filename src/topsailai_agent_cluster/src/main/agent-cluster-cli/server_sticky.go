package main

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// stickyProfileRelativePath is the default file that remembers the last Server
// that answered.
//
// It sits beside the per-user configuration and history files, so one directory
// holds this operator's CLI state. The name is a profile name, never a URL or a
// token: a URL would be a second spelling of a Server the operator already named,
// and a token in a state file would be a credential copy nobody rotates.
const stickyProfileRelativePath = ".topsailai/.topsailai_agent_cluster.server-profile"

// stickyProfilePath returns the configured file, or the per-user default.
//
// An empty result means no path could be resolved, which is not an error: the
// sticky preference is a convenience, and a CLI that refused to start because it
// could not name a file would be unusable for the reason it is least needed.
func stickyProfilePath(lookup func(string) string, home string) string {
	if configured := cliEnvironmentValue(lookup, cliServerProfileStickyFileEnv); configured != "" {
		return configured
	}
	if strings.TrimSpace(home) == "" {
		return ""
	}
	return filepath.Join(home, filepath.FromSlash(stickyProfileRelativePath))
}

// readStickyProfile returns the remembered profile name, or an empty string.
//
// Every failure yields an empty string rather than an error, because the file is
// advisory. A missing file is the normal first run, an unreadable file is a
// permissions problem the operator will notice elsewhere, and a stale name is
// handled by preferSticky. Turning any of those into a startup failure would make
// a convenience able to break the CLI.
func readStickyProfile(path string) string {
	if path == "" {
		return ""
	}
	content, err := os.ReadFile(path)
	if err != nil {
		return ""
	}
	return strings.TrimSpace(string(content))
}

// writeStickyProfile records the profile that answered.
//
// The write is best effort and its error is returned so the caller can report it
// as a diagnostic. A failed write must not fail the invocation: the request
// already succeeded, and refusing to report that because a preference file could
// not be written would turn a working command into a failure.
//
// The file is created with 0600 because it records which Server this operator
// uses, which is operational information rather than a secret, but a per-user
// state file has no reason to be readable by anyone else.
func writeStickyProfile(path, name string) error {
	if path == "" || name == "" {
		return nil
	}
	if err := os.MkdirAll(filepath.Dir(path), 0o700); err != nil {
		return fmt.Errorf("remember Server profile: %w", err)
	}
	if err := os.WriteFile(path, []byte(name+"\n"), 0o600); err != nil {
		return fmt.Errorf("remember Server profile: %w", err)
	}
	return nil
}

// preferSticky moves the remembered profile to the front of the candidate list.
//
// This is what keeps the CLI in the same world as the fleet. An Endpoint only
// reconnects on transport failure, so after a primary recovers the fleet stays on
// the secondary. A CLI that always probed from the head of the list would return
// to the primary and report an empty fleet, which reads as a total outage.
//
// The remaining candidates keep their configured order, so the preference is a
// rotation rather than a reordering: the operator's stated preference still
// decides everything after the remembered Server.
//
// A remembered name that is not in the list is ignored. That happens when the
// operator edits the group, and honouring it would mean probing a Server that is
// no longer configured.
//
// A group of one is returned unchanged, because there is nothing to prefer.
func preferSticky(candidates []ServerTarget, sticky string) []ServerTarget {
	if len(candidates) < 2 || sticky == "" {
		return candidates
	}
	preferred := make([]ServerTarget, 0, len(candidates))
	var remembered *ServerTarget
	for index := range candidates {
		if candidates[index].Profile == sticky {
			remembered = &candidates[index]
			continue
		}
		preferred = append(preferred, candidates[index])
	}
	if remembered == nil {
		return candidates
	}
	return append([]ServerTarget{*remembered}, preferred...)
}

// stickyProfilePathFromProcess is the shipped entry point. It reads the real
// environment and the real home directory once, so the resolution rules above stay
// testable while the binary still configures itself from its own process.
//
// An unresolvable home directory only means the default path is absent, which is
// not an error: the preference is advisory and its absence is the normal first
// run.
func stickyProfilePathFromProcess() string {
	home, err := os.UserHomeDir()
	if err != nil {
		home = ""
	}
	return stickyProfilePath(os.Getenv, home)
}
