package endpoint

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"fmt"
	"io"
	"os"
	"path/filepath"
	"time"

	"topsailai_agent_cluster/internal/adapter"
)

// Default bounds for one activation. They exist so a candidate that is a huge
// file, a symlink to a device, or a program that never answers cannot stall the
// Endpoint or exhaust memory while it is being validated.
const (
	// DefaultReplaceMaxBytes bounds the candidate executable size. A Provider CLI
	// is a static Go binary of roughly 13 MiB, so 64 MiB leaves room for a debug
	// build while still rejecting an accidental disk image.
	DefaultReplaceMaxBytes int64 = 64 << 20
	// DefaultReplaceSmokeTimeout bounds the candidate bootstrap and smoke probe.
	// It is deliberately short: a Provider CLI that cannot answer describe within
	// this window is not a candidate an operator should activate.
	DefaultReplaceSmokeTimeout = 20 * time.Second
)

// ReplaceRequest asks the Endpoint to activate one executable for one adapter.
//
// It is Endpoint-local administrative input. It never travels over the Server
// channel, because a Provider CLI version is an Endpoint deployment detail and
// the Cluster contract deliberately has no concept of one.
type ReplaceRequest struct {
	// AdapterID selects the configured adapter whose executable is replaced.
	AdapterID string `json:"adapter_id"`
	// Executable is the absolute path of the candidate program.
	Executable string `json:"executable"`
	// ExpectedSHA256 optionally pins the candidate digest. When it is set the
	// candidate must match it, so a request cannot activate a file that changed
	// after the operator computed the digest.
	ExpectedSHA256 string `json:"expected_sha256,omitempty"`
	// MaxBytes overrides the candidate size bound. Zero keeps the default.
	MaxBytes int64 `json:"max_bytes,omitempty"`
	// SmokeTimeoutMS overrides the bootstrap and smoke budget. Zero keeps the
	// default.
	SmokeTimeoutMS int64 `json:"smoke_timeout_ms,omitempty"`
}

// ReplaceResult reports what activation actually achieved.
//
// It distinguishes "the new version is serving and published" from "the previous
// version is still serving", because an operator must never read a failed
// activation as a successful one.
type ReplaceResult struct {
	AdapterID         string `json:"adapter_id"`
	Executable        string `json:"executable"`
	PreviousVersion   string `json:"previous_version"`
	EffectiveVersion  string `json:"effective_version"`
	EffectiveRevision string `json:"effective_revision"`
	// InFlight reports how many callers were still holding a version when the swap
	// happened. A non-zero value means the previous version is draining rather than
	// closed, which is expected and not a failure.
	InFlight int `json:"in_flight"`
	// Reverted reports that the swap was undone because publication failed.
	Reverted bool `json:"reverted"`
	// RevertReason names why the swap was undone.
	RevertReason string `json:"revert_reason,omitempty"`
}

// DescriptorPublisher republishes adapter capabilities after a local change.
//
// It is the seam that makes "the new version is active" and "the fleet can see
// the new version" the same event. Without it a replacement would be invisible
// until the next periodic collection, and a mutation admitted in between would be
// validated against capabilities that no longer describe the running program.
type DescriptorPublisher interface {
	RefreshDescriptors(context.Context, string) error
}

// Replacer activates one executable for one adapter without restarting the
// Endpoint and without touching any other adapter.
//
// The order of operations is load-bearing and must not be rearranged:
//
//  1. Resolve the adapter's current configuration, so the candidate inherits the
//     timeout, arguments and declared capabilities the operator configured.
//  2. Validate the candidate file itself: absolute path, regular file, executable
//     mode, bounded size, and the pinned digest when one was supplied.
//  3. Build the candidate through the registered factory. This is the protocol
//     bootstrap: the factory runs describe and negotiates the protocol version, so
//     an incompatible candidate fails here, before anything is swapped.
//  4. Run a bounded smoke probe against the candidate. A program that describes
//     itself but cannot answer discovery is not activatable.
//  5. Swap atomically. Only now does the running adapter change.
//  6. Republish the effective revision. If publication fails the swap is undone,
//     so the observable outcome is either "new version active and published" or
//     "previous version active".
//
// A failure at any step before 5 leaves the previous version serving and closes
// the candidate, so a rejected activation is not a partial one.
type Replacer struct {
	Registry  *adapter.Registry
	Publisher DescriptorPublisher
}

// Replace validates and activates one candidate executable for one adapter.
func (r *Replacer) Replace(ctx context.Context, request ReplaceRequest) (ReplaceResult, error) {
	if r == nil || r.Registry == nil {
		return ReplaceResult{}, errors.New("replacer requires an adapter registry")
	}
	if request.AdapterID == "" {
		return ReplaceResult{}, errors.New("adapter ID is required")
	}
	previousConfig, ok := r.Registry.Config(request.AdapterID)
	if !ok {
		return ReplaceResult{}, fmt.Errorf("adapter ID %q is not configured", request.AdapterID)
	}
	previousAdapter, ok := r.Registry.Get(request.AdapterID)
	if !ok {
		return ReplaceResult{}, fmt.Errorf("adapter ID %q has no instance", request.AdapterID)
	}
	previousDescriptor, err := previousAdapter.Describe(ctx)
	if err != nil {
		return ReplaceResult{}, fmt.Errorf("describe current adapter %q: %w", request.AdapterID, err)
	}
	if err := validateCandidateFile(request); err != nil {
		return ReplaceResult{}, err
	}
	candidateConfig := previousConfig
	candidateConfig.Command = request.Executable
	candidate, err := r.Registry.Prepare(ctx, candidateConfig)
	if err != nil {
		// The factory already ran describe and negotiated the protocol version, so
		// this error covers both "the file is not a Provider CLI" and "the protocol
		// is incompatible". Nothing has been swapped.
		return ReplaceResult{}, fmt.Errorf("bootstrap candidate %q: %w", request.Executable, err)
	}
	// From here the candidate owns a child process, so every failure path must
	// close it. A leaked candidate would leave a Provider CLI running that no
	// adapter references.
	activated := false
	defer func() {
		if !activated {
			_ = candidate.Close()
		}
	}()
	candidateDescriptor, err := candidate.Describe(ctx)
	if err != nil {
		return ReplaceResult{}, fmt.Errorf("describe candidate %q: %w", request.Executable, err)
	}
	if err := validateCandidateDescriptor(candidateDescriptor); err != nil {
		return ReplaceResult{}, err
	}
	if err := r.smoke(ctx, candidate, request); err != nil {
		return ReplaceResult{}, err
	}
	previous, err := r.Registry.ReplaceWithConfig(request.AdapterID, candidate, candidateConfig)
	if err != nil {
		return ReplaceResult{}, fmt.Errorf("activate candidate %q: %w", request.Executable, err)
	}
	activated = true
	result := ReplaceResult{
		AdapterID:         request.AdapterID,
		Executable:        request.Executable,
		PreviousVersion:   previousDescriptor.Version,
		EffectiveVersion:  candidateDescriptor.Version,
		EffectiveRevision: candidateDescriptor.Capabilities.Revision,
		InFlight:          r.Registry.InFlight(request.AdapterID),
	}
	if r.Publisher == nil {
		// Without a publisher the new version is active but the fleet still holds
		// the previous capabilities, so a mutation could be validated against a
		// description that no longer matches the running program. Undo the swap
		// rather than leave that window open.
		return r.revert(ctx, result, previous, previousConfig, previousDescriptor.Capabilities.Revision, errors.New("no descriptor publisher is configured"))
	}
	if err := r.Publisher.RefreshDescriptors(ctx, candidateDescriptor.ProviderType); err != nil {
		return r.revert(ctx, result, previous, previousConfig, previousDescriptor.Capabilities.Revision, fmt.Errorf("publish effective revision: %w", err))
	}
	return result, nil
}

// revert restores the previous version and reports why.
//
// It is used only after a successful swap, so the candidate is serving and the
// previous instance is retired. Two cases must both be handled, because they
// differ in whether the previous process still exists:
//
//   - Nothing held the previous instance when the swap happened, so it was closed
//     immediately. Restoring the closed instance would hand back a dead adapter,
//     so the previous version is rebuilt from the configuration it was configured
//     with. The executable path is the only field that names a version, so the
//     rebuilt instance is the same version with the same timeout, arguments and
//     declared capabilities.
//   - A caller still held it, so it is draining and still open. Restoring the
//     original record keeps that caller's reference attached to the instance that
//     is serving again, so its in-flight work finishes on the version it started
//     on and nothing closes it underneath.
//
// A failure to restore either way is reported explicitly, because the one outcome
// an operator must never misread is "the candidate is active and the fleet was not
// republished".
func (r *Replacer) revert(ctx context.Context, result ReplaceResult, previous adapter.Adapter, previousConfig adapter.Config, previousRevision string, cause error) (ReplaceResult, error) {
	if err := r.restore(ctx, result.AdapterID, previous, previousConfig); err != nil {
		result.Reverted = false
		result.RevertReason = fmt.Sprintf("restore previous version failed: %v", err)
		return result, fmt.Errorf("%w; restoring the previous version also failed: %v", cause, err)
	}
	result.Reverted = true
	result.RevertReason = cause.Error()
	result.EffectiveVersion = result.PreviousVersion
	result.EffectiveRevision = previousRevision
	return result, cause
}

// restore puts the previous version back in service.
//
// The draining instance is preferred because it is already running and already
// holds the references of any in-flight caller. When it is gone, the version is
// rebuilt from its configuration, which is the only way to serve a version whose
// process was closed at swap time.
func (r *Replacer) restore(ctx context.Context, adapterID string, previous adapter.Adapter, previousConfig adapter.Config) error {
	restoreErr := r.Registry.RestoreWithConfig(adapterID, previous, previousConfig)
	if restoreErr == nil {
		return nil
	}
	rebuilt, err := r.Registry.Prepare(ctx, previousConfig)
	if err != nil {
		return fmt.Errorf("%v; rebuilding the previous version also failed: %w", restoreErr, err)
	}
	if _, err := r.Registry.ReplaceWithConfig(adapterID, rebuilt, previousConfig); err != nil {
		_ = rebuilt.Close()
		return fmt.Errorf("%v; reinstating the rebuilt previous version also failed: %w", restoreErr, err)
	}
	return nil
}

// smoke runs one bounded discovery against the candidate.
//
// Discovery is the cheapest operation that proves the candidate can do real work
// rather than only answer describe. It is bounded by the request budget so a
// candidate that hangs is rejected instead of blocking activation forever.
func (r *Replacer) smoke(ctx context.Context, candidate adapter.Adapter, request ReplaceRequest) error {
	timeout := DefaultReplaceSmokeTimeout
	if request.SmokeTimeoutMS > 0 {
		timeout = time.Duration(request.SmokeTimeoutMS) * time.Millisecond
	}
	smokeCtx, cancel := context.WithTimeout(ctx, timeout)
	defer cancel()
	if _, err := candidate.Discover(smokeCtx, adapter.DiscoverRequest{TimeoutMS: timeout.Milliseconds()}); err != nil {
		return fmt.Errorf("smoke discovery failed for %q: %w", request.Executable, err)
	}
	return nil
}

// validateCandidateFile checks the candidate artifact itself.
//
// The checks are ordered cheapest first and every one of them is a property of
// the file, not of the program: a candidate that fails here was never executed.
func validateCandidateFile(request ReplaceRequest) error {
	if request.Executable == "" {
		return errors.New("candidate executable path is required")
	}
	if !filepath.IsAbs(request.Executable) {
		// A relative path would resolve against the Endpoint's working directory,
		// which is not the directory the operator typed it in.
		return fmt.Errorf("candidate executable path %q must be absolute", request.Executable)
	}
	info, err := os.Lstat(request.Executable)
	if err != nil {
		return fmt.Errorf("inspect candidate %q: %w", request.Executable, err)
	}
	if info.Mode()&os.ModeSymlink != 0 {
		// A symlink can be repointed after validation, so the digest that was
		// checked would no longer describe the program that runs. The operator can
		// pass the resolved path instead.
		return fmt.Errorf("candidate %q is a symlink; pass the resolved path", request.Executable)
	}
	if !info.Mode().IsRegular() {
		return fmt.Errorf("candidate %q is not a regular file", request.Executable)
	}
	if info.Mode().Perm()&0o111 == 0 {
		return fmt.Errorf("candidate %q is not executable", request.Executable)
	}
	maxBytes := request.MaxBytes
	if maxBytes <= 0 {
		maxBytes = DefaultReplaceMaxBytes
	}
	if info.Size() <= 0 {
		return fmt.Errorf("candidate %q is empty", request.Executable)
	}
	if info.Size() > maxBytes {
		return fmt.Errorf("candidate %q is %d bytes, above the %d byte bound", request.Executable, info.Size(), maxBytes)
	}
	if request.ExpectedSHA256 == "" {
		return nil
	}
	digest, err := fileSHA256(request.Executable)
	if err != nil {
		return err
	}
	if digest != request.ExpectedSHA256 {
		return fmt.Errorf("candidate %q digest %s does not match the expected %s", request.Executable, digest, request.ExpectedSHA256)
	}
	return nil
}

// validateCandidateDescriptor rejects a candidate that describes itself without
// the identity an operator surface needs.
func validateCandidateDescriptor(descriptor adapter.Descriptor) error {
	if descriptor.ProviderType == "" {
		return errors.New("candidate descriptor has no provider type")
	}
	if descriptor.Version == "" {
		return errors.New("candidate descriptor has no provider version")
	}
	if descriptor.Capabilities.Revision == "" {
		return errors.New("candidate descriptor has no capability revision")
	}
	return nil
}

// fileSHA256 returns the hex digest of one file.
func fileSHA256(path string) (string, error) {
	file, err := os.Open(path)
	if err != nil {
		return "", fmt.Errorf("open candidate %q: %w", path, err)
	}
	defer file.Close()
	hasher := sha256.New()
	if _, err := io.Copy(hasher, file); err != nil {
		return "", fmt.Errorf("hash candidate %q: %w", path, err)
	}
	return hex.EncodeToString(hasher.Sum(nil)), nil
}
