package node

import (
	"context"
	"errors"
	"time"
)

// identityPollInterval is how often the running Node checks whether the identity
// file changed.
//
// The check reads a file of about 85 bytes, so a short interval costs almost
// nothing. It is a poll rather than a filesystem notification because the standard
// library has no portable notification API: a notification library would be a
// third-party dependency, and the design forbids an OS-specific mechanism on a
// project that supports Linux, macOS and Windows from one binary.
const identityPollInterval = time.Second

// watchIdentity adopts a regenerated identity while the Node keeps running.
//
// This is what makes `connector-node regenerate` mean what the design says it
// means. Regeneration is a separate process that rewrites the identity file and
// exits; without a watcher the running Node would keep serving the pair it read at
// startup, so the old token would keep working and the new one would be refused.
// The design states that regeneration invalidates the previous token immediately
// and drops the live channel, and both of those are this function's job.
//
// The comparison is on the pair itself, not on the file's modification time or
// size. Both of those are unreliable here: a regenerated pair has exactly the same
// byte length as the pair it replaces, and a rewrite can land inside the same
// modification-time tick as the read that produced the current identity. A stamp
// comparison therefore reports "unchanged" for a file that holds a different
// credential, which is the one case this function exists to notice. Reading the
// file and comparing the value is the only signal that cannot miss a regeneration.
//
// The watcher updates the holder before it signals, so a reconnect that starts
// because of the signal already dials with the new pair. The signal is advisory:
// its only purpose is to drop a channel that was authenticated with a credential
// that no longer exists.
//
// A file that cannot be read is logged once and skipped, and the previous identity
// stays in force. Adopting a half-written or malformed file would leave the Node
// serving an identity it cannot parse, which is worse than serving the old one
// until the operator fixes the file. The warning is logged once per distinct
// problem rather than once per poll, because a poll that repeats the same warning
// every second buries the first occurrence.
func (d *Dialer) watchIdentity(ctx context.Context, changes chan<- struct{}) {
	if d.identityPath == "" {
		return
	}

	ticker := time.NewTicker(identityPollInterval)
	defer ticker.Stop()

	// lastProblem suppresses a repeated warning. An empty value means the last
	// poll found nothing to report.
	lastProblem := ""

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}

		identity, err := LoadIdentity(d.identityPath)
		if err != nil {
			problem := describeIdentityProblem(err)
			if problem != lastProblem {
				lastProblem = problem
				d.logger.Warn("identity file could not be read; keeping the identity in force",
					"node_id", d.holder.Current().ID,
					"error", err,
				)
			}
			continue
		}
		lastProblem = ""

		if !d.holder.Replace(identity) {
			// The file holds the pair already in force, so nothing about the
			// Node's authority changed and the live channel stays up.
			continue
		}

		d.logger.Info("identity file changed; adopting the new pair and dropping the channel",
			"node_id", identity.ID,
		)

		// A buffered send keeps the watcher from blocking when the dialer is
		// between connections. A pending signal is drained before the next dial,
		// so a change that happened while the Node was disconnected does not drop
		// the channel that is about to be established with the new identity.
		select {
		case changes <- struct{}{}:
		default:
		}
	}
}

// describeIdentityProblem reduces a load failure to a stable description, so the
// watcher can tell a new problem from the same problem seen again.
//
// The error text is not used directly because it embeds the file path, which is
// constant, and a wrapped error whose text varied per poll would defeat the
// suppression it is meant to drive.
func describeIdentityProblem(err error) string {
	if errors.Is(err, ErrIdentityMissing) {
		return "missing"
	}
	return "malformed"
}

// discardPendingIdentityChange removes a change signal that arrived while no
// channel was live.
//
// Without this, a regeneration during a reconnect delay would leave a signal in
// the buffer, and the next loop iteration would drop the freshly established
// channel even though it was authenticated with the new pair.
func discardPendingIdentityChange(changes <-chan struct{}) {
	select {
	case <-changes:
	default:
	}
}

// identityChangeContext derives a context that is cancelled when the identity
// changes, so one channel is dropped without ending the reconnect loop.
//
// The returned stop function must be called when the connection ends, otherwise
// the goroutine outlives the connection it was installed for.
func identityChangeContext(ctx context.Context, changes <-chan struct{}) (context.Context, context.CancelFunc) {
	changeCtx, cancel := context.WithCancel(ctx)
	if changes == nil {
		return changeCtx, cancel
	}

	// done releases the goroutine when the connection ends for another reason, so
	// a connection that closes normally does not leave a goroutine waiting on a
	// signal that will never arrive.
	done := make(chan struct{})
	go func() {
		select {
		case <-changes:
			cancel()
		case <-done:
		}
	}()

	return changeCtx, func() {
		close(done)
		cancel()
	}
}
