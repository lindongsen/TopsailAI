// Package lock provides the per-task runtime lock.
//
// The lock is a kernel-level advisory lock (flock) held on the task's .lock
// file. Because it is tied to an open file descriptor, the kernel releases it
// automatically when the holding process dies. A crashed or killed run
// therefore cannot leave a task permanently locked, which a create-and-delete
// marker file cannot guarantee.
//
// The lock is deliberately a separate file rather than being taken on the .md
// content file. A lock is bound to a file, not to a path: editing or replacing
// the .md would move the lock to a new file and let the same task run twice.
//
// While a supervisor holds the lock it also writes a Record into the file. The
// flock answers "is a scheduler supervising this task right now"; the record
// answers "which run was in flight when the last supervisor died". The second
// question matters because a run is a separate process that outlives the
// scheduler: after a restart the lock is free while the run may still be
// working, and only the record says what to go and check.
package lock

import (
	"bytes"
	"encoding/json"
	"fmt"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/gofrs/flock"
)

// Lock is a held or attempted task lock.
type Lock struct {
	path string
	file *flock.Flock
	held bool
}

// TryAcquire attempts to take the lock at path without blocking.
//
// It returns a non-nil Lock and held=true when the lock was taken. When another
// process already holds it, it returns a Lock with held=false and no error: a
// busy task is a normal scheduling outcome, not a failure. Waiting would only
// queue runs that the next tick attempts again anyway.
func TryAcquire(path string) (*Lock, bool, error) {
	if err := os.MkdirAll(filepath.Dir(path), 0o755); err != nil {
		return nil, false, fmt.Errorf("create lock directory for %q: %w", path, err)
	}

	file := flock.New(path)
	acquired, err := file.TryLock()
	if err != nil {
		return nil, false, fmt.Errorf("acquire lock %q: %w", path, err)
	}
	return &Lock{path: path, file: file, held: acquired}, acquired, nil
}

// Held reports whether this Lock currently holds the underlying lock.
func (l *Lock) Held() bool {
	return l != nil && l.held
}

// Path returns the lock file path.
func (l *Lock) Path() string {
	if l == nil {
		return ""
	}
	return l.path
}

// Release drops the lock. It is safe to call on a Lock that was never held and
// safe to call more than once.
//
// The .lock file itself is left on disk on purpose: it is a handle, not a state
// marker, so its presence does not mean the task is running. Its content is the
// supervisor's record, which the caller clears once the run is known to have
// ended; Release does not clear it, because a supervisor that ends abnormally
// must leave the breadcrumb behind for the next start to reconcile.
func (l *Lock) Release() error {
	if l == nil || !l.held {
		return nil
	}
	l.held = false
	if err := l.file.Unlock(); err != nil {
		return fmt.Errorf("release lock %q: %w", l.path, err)
	}
	return nil
}

// Record is the breadcrumb a supervisor writes into the lock file while it
// supervises a run.
//
// The flock remains the authority for "a scheduler is supervising this task".
// The record answers the question the flock cannot: which run was in flight when
// the last supervisor died. A run is a separate process that outlives the
// scheduler, so after a restart the lock is free while the run may still be
// working, and only the record says what to go and check.
//
// The record is advisory. A missing, empty or unreadable record means "unknown",
// never "nothing was running", because a supervisor that died before writing it
// leaves no trace.
type Record struct {
	// RunID is the provider-defined run identity, for example a session id.
	RunID string `json:"run_id"`
	// Provider is the provider name that owns the run, so a restart can ask the
	// same provider about it.
	Provider string `json:"provider"`
	// PID is the run's process id when the provider reported one. It is for
	// observability only: a pid can be reused, so it must never be the sole key
	// for a later check.
	PID int `json:"pid"`
	// StartedAt is when supervision began.
	StartedAt time.Time `json:"started_at"`
	// SchedulerPID is the process that wrote the record. It identifies the
	// supervisor that died, which is what makes a stale record recognisable.
	SchedulerPID int `json:"scheduler_pid"`
}

// IsZero reports whether the record carries no run identity.
func (r Record) IsZero() bool {
	return strings.TrimSpace(r.RunID) == ""
}

// WriteRecord stores the record in the lock file.
//
// The file is rewritten in place rather than replaced through a temporary file
// and a rename. A rename would give the path a new inode, and the flock is bound
// to the inode: the next process would open the new file, lock it successfully
// and mutual exclusion would be silently gone. That is the same failure this
// package already avoids by not locking on the .md content file.
//
// The write is not atomic, so a reader may observe a partial document. ReadRecord
// treats that as "no record" rather than an error, because a torn record is
// exactly as informative as a missing one.
func (l *Lock) WriteRecord(record Record) error {
	if l == nil || l.path == "" {
		return fmt.Errorf("write lock record: no lock path")
	}

	document, err := json.Marshal(record)
	if err != nil {
		return fmt.Errorf("encode lock record for %q: %w", l.path, err)
	}
	document = append(document, '\n')

	// The flock handle is opened read-only, so the record needs its own
	// descriptor. Writing to the same inode does not disturb the lock.
	file, err := os.OpenFile(l.path, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o600)
	if err != nil {
		return fmt.Errorf("open lock file %q for writing: %w", l.path, err)
	}
	if _, writeErr := file.Write(document); writeErr != nil {
		_ = file.Close()
		return fmt.Errorf("write lock record to %q: %w", l.path, writeErr)
	}
	if syncErr := file.Sync(); syncErr != nil {
		_ = file.Close()
		return fmt.Errorf("sync lock record to %q: %w", l.path, syncErr)
	}
	if closeErr := file.Close(); closeErr != nil {
		return fmt.Errorf("close lock file %q: %w", l.path, closeErr)
	}
	return nil
}

// ClearRecord empties the lock file after a run is known to have ended.
//
// Clearing rather than deleting keeps the inode, so the flock stays valid and a
// later reader cannot mistake an empty file for a missing one.
func (l *Lock) ClearRecord() error {
	if l == nil || l.path == "" {
		return fmt.Errorf("clear lock record: no lock path")
	}
	file, err := os.OpenFile(l.path, os.O_WRONLY|os.O_CREATE|os.O_TRUNC, 0o600)
	if err != nil {
		return fmt.Errorf("open lock file %q for clearing: %w", l.path, err)
	}
	if closeErr := file.Close(); closeErr != nil {
		return fmt.Errorf("close lock file %q after clearing: %w", l.path, closeErr)
	}
	return nil
}

// ReadRecord returns the record stored in the lock file at path.
//
// A missing file, an empty file and an unparseable file all report a zero Record
// with no error. None of them is evidence that nothing was running: they only
// mean the previous supervisor left no usable breadcrumb, so the caller must
// treat the run as unknown rather than absent.
func ReadRecord(path string) (Record, error) {
	content, err := os.ReadFile(path)
	if err != nil {
		if os.IsNotExist(err) {
			return Record{}, nil
		}
		return Record{}, fmt.Errorf("read lock file %q: %w", path, err)
	}
	if len(bytes.TrimSpace(content)) == 0 {
		return Record{}, nil
	}

	var record Record
	if decodeErr := json.Unmarshal(content, &record); decodeErr != nil {
		return Record{}, nil
	}
	return record, nil
}
