package endpoint

import (
	"context"
	"fmt"
	"os"
	"os/signal"
	"sync"
	"syscall"
)

// AllowlistFile loads an allowlist from disk and reloads it on demand.
//
// Reload is explicit rather than periodic: a signal or an administrative call
// triggers it, so the policy in force never drifts silently from the file on disk
// and a busy Endpoint does not stat the file for every command.
type AllowlistFile struct {
	Path      string
	Allowlist *Allowlist
}

// LoadAllowlistFile reads and validates the allowlist file at path.
func LoadAllowlistFile(path string) (*AllowlistFile, error) {
	if path == "" {
		return nil, fmt.Errorf("allowlist file path is required")
	}
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, fmt.Errorf("read allowlist file %q: %w", path, err)
	}
	list, err := LoadAllowlist(data)
	if err != nil {
		return nil, fmt.Errorf("parse allowlist file %q: %w", path, err)
	}
	return &AllowlistFile{Path: path, Allowlist: list}, nil
}

// Reload re-reads the file and swaps the entries atomically. A read or parse
// failure keeps the previous list in force and returns the error, so a broken
// edit cannot disable or widen the policy.
func (f *AllowlistFile) Reload() error {
	data, err := os.ReadFile(f.Path)
	if err != nil {
		return fmt.Errorf("read allowlist file %q: %w", f.Path, err)
	}
	if err := f.Allowlist.Reload(data); err != nil {
		return fmt.Errorf("parse allowlist file %q: %w", f.Path, err)
	}
	return nil
}

// WatchReload reloads the allowlist on SIGHUP until the returned stop function is
// called or the context is cancelled.
//
// SIGHUP is registered explicitly because Go terminates a process on SIGHUP by
// default, so without this handler the reload signal would kill the Endpoint.
// The returned stop function unregisters the handler, cancels the watcher and
// waits for it to exit, so it is safe to defer regardless of defer order.
func (f *AllowlistFile) WatchReload(ctx context.Context, onReload func(error)) (func(), error) {
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
				if onReload != nil {
					onReload(f.Reload())
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
