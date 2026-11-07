package topsailai

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"
)

// sessionInfoExecutable is the provider's single-session inspection entry point.
// It is a sibling of the configured provider executable, not a subcommand of it.
const sessionInfoExecutable = "topsailai_session_info"

// errSessionInfoUnavailable reports that the provider session inspection entry
// point could not be located next to the configured executable.
var errSessionInfoUnavailable = errors.New("provider session inspection executable is unavailable")

// sessionInfo is the provider's own single-session document, reduced to the
// fields that establish a working directory.
type sessionInfo struct {
	SessionID        string `json:"session_id"`
	ProjectWorkspace string `json:"project_workspace"`
	Pwd              string `json:"pwd"`
}

// sessionInfoPath resolves the session inspection executable beside the
// configured provider executable.
//
// The provider installs its entry points as siblings, so the directory of the
// configured executable is the only trustworthy location. Resolving through PATH
// would let an unrelated program earlier on PATH answer for the provider.
func sessionInfoPath(executable string) (string, error) {
	directory := filepath.Dir(executable)
	if !filepath.IsAbs(directory) {
		return "", errSessionInfoUnavailable
	}
	candidate := filepath.Join(directory, sessionInfoExecutable)
	info, err := os.Stat(candidate)
	if err != nil || info.IsDir() {
		return "", errSessionInfoUnavailable
	}
	return candidate, nil
}

// readSessionInfo reads the provider's single-session document.
func (a *Adapter) readSessionInfo(ctx context.Context, providerKey string) (sessionInfo, error) {
	path, err := sessionInfoPath(a.config.Executable)
	if err != nil {
		return sessionInfo{}, err
	}
	output, err := a.runner.Run(ctx, path, []string{providerKey, "--json"}, nil)
	if err != nil {
		return sessionInfo{}, fmt.Errorf("read session info for %q: %w", providerKey, err)
	}
	var info sessionInfo
	if err := json.Unmarshal(output, &info); err != nil {
		return sessionInfo{}, fmt.Errorf("decode session info for %q: %w", providerKey, err)
	}
	if info.SessionID != "" && info.SessionID != providerKey {
		return sessionInfo{}, fmt.Errorf("session info for %q reported session %q", providerKey, info.SessionID)
	}
	return info, nil
}
