package provider

import (
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"
)

// Resolver turns a provider executable path into a Provider.
//
// A provider is an independent program, so the scheduler must not assume where
// it lives. The path is given explicitly, either by the scheduler configuration
// or by the task, and the resolver only checks that the file is there and
// runnable. There is no folder layout to follow: a provider may sit anywhere,
// and a compiled binary, a shell script and a Python script are equally valid
// because the scheduler never inspects which one it is.
type Resolver struct {
	// callTimeout bounds one protocol call.
	callTimeout time.Duration
	// maxOutputBytes caps retained output from a protocol call.
	maxOutputBytes int
}

// ResolverOptions configures a provider resolver.
type ResolverOptions struct {
	// CallTimeout bounds one protocol call. Zero means DefaultCallTimeout.
	CallTimeout time.Duration
	// MaxOutputBytes caps retained output. Zero means the runner default.
	MaxOutputBytes int
}

// NewResolver returns a resolver for provider executables given by path.
func NewResolver(options ResolverOptions) *Resolver {
	return &Resolver{
		callTimeout:    options.CallTimeout,
		maxOutputBytes: options.MaxOutputBytes,
	}
}

// Provider returns the provider implemented by the executable at path.
//
// A relative path resolves against the working directory, the same rule the
// tasks root and the control socket follow, so one rule covers every path the
// scheduler accepts.
//
// The executable must exist and be a file. A missing executable is reported
// here, before the protocol call, so a misconfigured provider fails with a clear
// reason instead of a confusing protocol error. The daemon also calls Check when
// it scans the task tree, so a task naming a missing provider is rejected at
// schedule time rather than at its first due time.
func (r *Resolver) Provider(path string) (Provider, error) {
	executable, err := r.Check(path)
	if err != nil {
		return nil, err
	}

	return NewCLI(CLIOptions{
		Name:           executable,
		Command:        executable,
		Timeout:        r.callTimeout,
		MaxOutputBytes: r.maxOutputBytes,
	})
}

// Check verifies that path names a provider executable and returns its absolute
// path.
//
// It is the existence check without the adapter, so the task scan can reject a
// misconfigured task without building a provider it will not use. Both callers
// share this one implementation, so the scan and the run can never disagree
// about whether a provider is usable.
func (r *Resolver) Check(path string) (string, error) {
	executable, err := r.Executable(path)
	if err != nil {
		return "", err
	}

	info, statErr := os.Stat(executable)
	if statErr != nil {
		if os.IsNotExist(statErr) {
			return "", fmt.Errorf("provider executable %s does not exist", executable)
		}
		return "", fmt.Errorf("stat provider executable %s: %w", executable, statErr)
	}
	if info.IsDir() {
		return "", fmt.Errorf("provider executable %s is a directory", executable)
	}
	return executable, nil
}

// Executable returns the absolute path of a provider executable.
//
// The path is returned whether or not the file exists, so a caller can report
// the expected location in an error instead of only saying the provider is
// unknown.
func (r *Resolver) Executable(path string) (string, error) {
	trimmed := strings.TrimSpace(path)
	if trimmed == "" {
		return "", fmt.Errorf("provider path must not be empty")
	}
	if filepath.IsAbs(trimmed) {
		return filepath.Clean(trimmed), nil
	}
	absolute, err := filepath.Abs(trimmed)
	if err != nil {
		return "", fmt.Errorf("resolve provider path %q: %w", trimmed, err)
	}
	return absolute, nil
}
