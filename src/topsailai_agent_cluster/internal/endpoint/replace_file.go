package endpoint

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"os/signal"
	"path/filepath"
	"sync"
	"syscall"
)

// replaceResultFileName is the fixed name of the correlated answer document.
//
// It is fixed rather than configurable so the controller and the Endpoint cannot
// disagree about where the answer is written. The request path is the only knob,
// and the answer always sits beside it.
const replaceResultFileName = "replace-result.json"

// ReplaceFileRequest is one Endpoint-local activation request.
//
// It is written by the node controller and consumed by the Endpoint. It never
// travels over the Server channel: a Provider CLI version is an Endpoint
// deployment detail, and the Cluster contract deliberately has no concept of one.
type ReplaceFileRequest struct {
	// RequestID correlates the answer with this request. The controller waits for
	// a result carrying the same value, so a stale answer from an earlier
	// activation can never be read as the outcome of this one.
	RequestID string `json:"request_id"`
	// AdapterID selects the configured adapter whose executable is replaced.
	AdapterID string `json:"adapter_id"`
	// Executable is the absolute path of the candidate program.
	Executable string `json:"executable"`
	// ExpectedSHA256 optionally pins the candidate digest.
	ExpectedSHA256 string `json:"expected_sha256,omitempty"`
	// MaxBytes overrides the candidate size bound. Zero keeps the default.
	MaxBytes int64 `json:"max_bytes,omitempty"`
	// SmokeTimeoutMS overrides the bootstrap and smoke budget. Zero keeps the
	// default.
	SmokeTimeoutMS int64 `json:"smoke_timeout_ms,omitempty"`
}

// ReplaceFileResult is the correlated answer to one request.
//
// It always states whether the requested version is the one now serving, because
// an operator must never read a rejected activation as a successful one.
type ReplaceFileResult struct {
	RequestID string        `json:"request_id"`
	OK        bool          `json:"ok"`
	Result    ReplaceResult `json:"result"`
	Error     string        `json:"error,omitempty"`
}

// ReplaceFile consumes one activation request document per reload signal.
//
// The Endpoint has no HTTP listener and the node controller has no HTTP client, so
// the established convention for a local administrative change is a configured
// file plus SIGHUP, exactly as the command allowlist, the control action catalog
// and the access policy already work. Reusing it keeps one transport for every
// local administrative change instead of inventing a second one for activation.
type ReplaceFile struct {
	// Path is the request document the controller writes.
	Path string
	// Replacer performs the activation.
	Replacer *Replacer
	// LogConsumed reports that a request document was consumed. The Endpoint always
	// sets it, because consuming a request deletes an operator-written file and a
	// deletion must be observable. It is optional only so a test can stay silent.
	LogConsumed func(string)
	mu          sync.Mutex
}

// ResultPath returns the answer document path for the configured request path.
func (f *ReplaceFile) ResultPath() string {
	if f == nil || f.Path == "" {
		return ""
	}
	return filepath.Join(filepath.Dir(f.Path), replaceResultFileName)
}

// Process consumes the request document when one is present.
//
// A missing request is not an error. SIGHUP is shared with the allowlist, the
// control action catalog and the access policy, so most signals arrive with no
// activation pending, and treating that as a failure would report an error on
// every unrelated reload.
//
// A present request is consumed before it is acted on. Keeping it would let the
// next unrelated reload signal replay an activation the operator asked for once,
// including after a restart, so the document is removed as soon as it is read.
//
// The returned result is nil when no request was present. When a request was
// present the result is always written, including for a rejected one, so the
// controller learns the outcome instead of waiting for a deadline.
func (f *ReplaceFile) Process(ctx context.Context) (*ReplaceFileResult, error) {
	if f == nil || f.Replacer == nil {
		return nil, errors.New("replace file requires a replacer")
	}
	if f.Path == "" {
		return nil, errors.New("replace file path is required")
	}
	f.mu.Lock()
	defer f.mu.Unlock()
	data, err := os.ReadFile(f.Path)
	if err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil, nil
		}
		return nil, fmt.Errorf("read replace request %q: %w", f.Path, err)
	}
	if removeErr := os.Remove(f.Path); removeErr != nil {
		return nil, fmt.Errorf("consume replace request %q: %w", f.Path, removeErr)
	}
	if f.LogConsumed != nil {
		f.LogConsumed(f.Path)
	}
	var request ReplaceFileRequest
	if err := json.Unmarshal(data, &request); err != nil {
		result := ReplaceFileResult{Error: fmt.Sprintf("decode replace request: %v", err)}
		if writeErr := f.writeResult(result); writeErr != nil {
			return &result, fmt.Errorf("decode replace request %q: %w; writing the result also failed: %v", f.Path, err, writeErr)
		}
		return &result, fmt.Errorf("decode replace request %q: %w", f.Path, err)
	}
	if request.RequestID == "" {
		// The answer cannot be correlated without an ID, so it is written with an
		// empty one. The controller reports a timeout and points at the Endpoint
		// log, which is the only place the rejection reason survives.
		result := ReplaceFileResult{Error: "request_id is required"}
		if writeErr := f.writeResult(result); writeErr != nil {
			return &result, fmt.Errorf("replace request %q has no request_id; writing the result also failed: %v", f.Path, writeErr)
		}
		return &result, fmt.Errorf("replace request %q has no request_id", f.Path)
	}
	replaceResult, replaceErr := f.Replacer.Replace(ctx, ReplaceRequest{
		AdapterID:      request.AdapterID,
		Executable:     request.Executable,
		ExpectedSHA256: request.ExpectedSHA256,
		MaxBytes:       request.MaxBytes,
		SmokeTimeoutMS: request.SmokeTimeoutMS,
	})
	result := ReplaceFileResult{RequestID: request.RequestID, OK: replaceErr == nil, Result: replaceResult}
	if replaceErr != nil {
		result.Error = replaceErr.Error()
	}
	if writeErr := f.writeResult(result); writeErr != nil {
		return &result, fmt.Errorf("activation failed: %w; writing the result also failed: %v", replaceErr, writeErr)
	}
	return &result, replaceErr
}

// writeResult publishes the answer document atomically.
//
// A partially written answer would be read by the controller as a malformed
// document, so the content is written to a sibling temporary file and renamed into
// place. The temporary file is removed on every failure path; that cleanup is not
// logged because it is an internal artifact of this write, not an operator file.
func (f *ReplaceFile) writeResult(result ReplaceFileResult) error {
	data, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		return fmt.Errorf("encode replace result: %w", err)
	}
	data = append(data, '\n')
	path := f.ResultPath()
	temp, err := os.CreateTemp(filepath.Dir(path), ".replace-result-*")
	if err != nil {
		return fmt.Errorf("create replace result %q: %w", path, err)
	}
	tempPath := temp.Name()
	if _, err := temp.Write(data); err != nil {
		_ = temp.Close()
		_ = os.Remove(tempPath)
		return fmt.Errorf("write replace result %q: %w", path, err)
	}
	if err := temp.Close(); err != nil {
		_ = os.Remove(tempPath)
		return fmt.Errorf("close replace result %q: %w", path, err)
	}
	if err := os.Chmod(tempPath, 0o644); err != nil {
		_ = os.Remove(tempPath)
		return fmt.Errorf("set replace result mode %q: %w", path, err)
	}
	if err := os.Rename(tempPath, path); err != nil {
		_ = os.Remove(tempPath)
		return fmt.Errorf("publish replace result %q: %w", path, err)
	}
	return nil
}

// WatchReload processes a request document on SIGHUP until stop is called.
//
// SIGHUP is registered explicitly because Go terminates a process on SIGHUP by
// default, so without this handler the reload signal would kill the Endpoint. The
// returned stop function unregisters the handler, cancels the watcher and waits
// for it to exit, so it is safe to defer regardless of defer order.
func (f *ReplaceFile) WatchReload(ctx context.Context, onResult func(ReplaceFileResult, error)) (func(), error) {
	if f == nil || f.Path == "" {
		return nil, errors.New("replace file path is required")
	}
	watchCtx, cancel := context.WithCancel(ctx)
	signals := make(chan os.Signal, 1)
	signal.Notify(signals, syscall.SIGHUP)
	done := make(chan struct{})
	go func() {
		defer close(done)
		for {
			select {
			case <-watchCtx.Done():
				return
			case <-signals:
				result, err := f.Process(watchCtx)
				if result == nil && err == nil {
					continue
				}
				if onResult != nil {
					if result == nil {
						onResult(ReplaceFileResult{}, err)
						continue
					}
					onResult(*result, err)
				}
			}
		}
	}()
	var once sync.Once
	stop := func() {
		once.Do(func() {
			signal.Stop(signals)
			cancel()
			<-done
		})
	}
	return stop, nil
}
