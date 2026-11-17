package main

import (
	"context"
	"errors"
	"log/slog"
	"strings"
	"time"

	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// writeLivenessProbe is the statement the watchdog uses to prove the database can
// still accept a write.
//
// It writes a PRAGMA rather than a business row, because the probe must not change
// any table the Server serves. PRAGMA user_version is stored in the database header,
// so writing it takes the same write lock a business write takes and fails the same
// way when another holder keeps SHARED. That makes it a faithful probe: it cannot
// succeed while a real write would fail, and it cannot fail while a real write would
// succeed.
const writeLivenessProbe = `PRAGMA user_version = 1`

// errWriteLivenessLost reports that the database stopped accepting writes for
// longer than the configured budget.
var errWriteLivenessLost = errors.New("database stopped accepting writes")

// writeLivenessProbeTimeout bounds one probe attempt.
//
// It must be longer than the driver's busy_timeout, which is 5000ms in the DSN.
// If the probe context expired first, the driver would return a context deadline
// instead of SQLITE_BUSY, and the watchdog would see an error it cannot classify as
// lock contention. With the default interval of five seconds that would make the
// watchdog treat the very first probe during any transient lock as unrecoverable and
// end the process, which is a false positive that restarts a healthy Server. Ten
// seconds leaves the driver room to report the real lock error.
const writeLivenessProbeTimeout = 10 * time.Second

// isLockContention reports whether an error is the transient class the watchdog
// waits on.
//
// Only lock contention is retried. A disk-full, read-only-volume or corrupt-file
// error is unrecoverable, and waiting on it would keep the Server running while it
// cannot persist anything, which is the failure this watchdog exists to end. Those
// errors are returned immediately so the process exits without waiting out the
// budget.
func isLockContention(err error) bool {
	if err == nil {
		return false
	}
	message := strings.ToLower(err.Error())
	return strings.Contains(message, "locked") || strings.Contains(message, "busy")
}

// runWriteLiveness proves on a fixed interval that the database still accepts a
// write, and reports a lost write capability once the budget is exhausted.
//
// It exists because of a measured production outage. The Server ran for two hours
// and fifty-six minutes while every write failed with SQLITE_BUSY, and the only
// trace was a repeated error log line. Reads kept working, so the API answered and
// the process looked alive, while every state change was silently discarded. A
// Server that cannot write is not serving its purpose, and continuing to run hides
// that from the operator and from any supervisor that only checks liveness.
//
// The budget is the single knob the coding requirement asks for. A zero budget
// disables the watchdog, which is the right choice only when the operator prefers a
// blocked Server to a restarted one. A positive budget bounds how long the process
// may keep running without being able to persist anything.
//
// The probe runs on its own connection from the pool, so it observes the same lock
// state a business write observes. It never retries a probe that failed for a
// non-lock reason, because that class cannot be fixed by waiting.
func runWriteLiveness(ctx context.Context, logger *slog.Logger, store *serverstorage.Store, interval, budget time.Duration) error {
	if budget <= 0 {
		logger.Info("write liveness watchdog disabled", "reason", "budget is zero")
		return nil
	}
	if interval <= 0 {
		interval = time.Second
	}
	logger.Info("write liveness watchdog started", "interval", interval.String(), "budget", budget.String())

	var failingSince time.Time
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return nil
		case <-ticker.C:
		}

		// The probe gets its own timeout rather than reusing the interval. Reusing
		// the interval made the probe context expire before the driver's busy_timeout
		// could report SQLITE_BUSY, so the watchdog saw a context deadline it could
		// not classify as lock contention and treated a transient lock as
		// unrecoverable. That would end the process on the first probe during any
		// lock, which is a false positive worse than the outage it prevents.
		probeCtx, cancel := context.WithTimeout(ctx, writeLivenessProbeTimeout)
		_, err := store.DB().ExecContext(probeCtx, writeLivenessProbe)
		cancel()

		if err == nil {
			if !failingSince.IsZero() {
				logger.Info("database accepts writes again", "blocked_for", time.Since(failingSince).String())
				failingSince = time.Time{}
			}
			continue
		}
		if ctx.Err() != nil {
			return nil
		}
		if !isLockContention(err) {
			// Unrecoverable: waiting cannot help, so report it now rather than
			// spending the budget on a condition that will not clear.
			logger.Error("database write probe failed with an unrecoverable error", "error", err)
			return err
		}
		if failingSince.IsZero() {
			failingSince = time.Now()
			logger.Warn("database write probe failed", "error", err, "budget", budget.String())
			continue
		}
		blockedFor := time.Since(failingSince)
		if blockedFor < budget {
			continue
		}
		logger.Error("database stopped accepting writes for longer than the budget",
			"error", err, "blocked_for", blockedFor.String(), "budget", budget.String())
		return errWriteLivenessLost
	}
}
