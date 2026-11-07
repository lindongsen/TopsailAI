package topsailai

import (
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"strings"
)

// errDirectoryUnresolved reports that no session working directory could be
// established. It is a definite failure, not an unknown effect: nothing ran.
var errDirectoryUnresolved = errors.New("session working directory is unresolved")

// errArgumentNotConfined reports that an argument would leave the session
// working directory. It is a definite failure, not an unknown effect.
var errArgumentNotConfined = errors.New("argument is not confined to the session working directory")

// sessionDirectory resolves the working directory for one session.
//
// The provider records two candidate directories. project_workspace is the
// project the session belongs to, and pwd is the directory the session was
// started from; the project workspace wins because it is the stable location the
// operator means by "the session's folder". When neither resolves to an existing
// directory the call fails closed: falling back to the Endpoint process working
// directory would run the command somewhere the operator never selected.
func sessionDirectory(projectWorkspace, pwd string) (string, error) {
	for _, candidate := range []string{projectWorkspace, pwd} {
		trimmed := strings.TrimSpace(candidate)
		if trimmed == "" {
			continue
		}
		if !filepath.IsAbs(trimmed) {
			continue
		}
		// Resolve symlinks before the directory check so the confinement decision
		// is made on the real location rather than on a link that points elsewhere.
		resolved, err := filepath.EvalSymlinks(trimmed)
		if err != nil {
			continue
		}
		info, err := os.Stat(resolved)
		if err != nil || !info.IsDir() {
			continue
		}
		return resolved, nil
	}
	return "", errDirectoryUnresolved
}

// confineArguments rejects arguments that would address a location outside the
// session working directory.
//
// The program name is excluded because it is administrative configuration
// governed by the allowlist, while the remaining tokens are operator input. An
// absolute argument addresses a fixed location the operator did not select, and a
// parent-traversal element walks out of the directory. Both are rejected on the
// token itself; the directory confinement is additionally checked on the resolved
// working directory, because a symlinked directory can point anywhere.
func confineArguments(argv []string) error {
	if len(argv) == 0 {
		return errors.New("argv is required")
	}
	for index, token := range argv[1:] {
		if filepath.IsAbs(token) {
			return fmt.Errorf("%w: argument %d is an absolute path", errArgumentNotConfined, index+1)
		}
		for _, element := range strings.Split(token, "/") {
			if element == ".." {
				return fmt.Errorf("%w: argument %d traverses a parent directory", errArgumentNotConfined, index+1)
			}
		}
	}
	return nil
}
