package node

import (
	"context"
	"errors"
	"time"
)

// identityPollInterval is how often the running Node checks whether the identity
// or credential file changed.
//
// The check reads two small files, so a short interval costs almost nothing. It is a
// poll rather than a filesystem notification because the standard library has no
// portable notification API: a notification library would be a third-party
// dependency, and the design forbids an OS-specific mechanism on a project that
// supports Linux, macOS and Windows from one binary.
const identityPollInterval = time.Second

// watchIdentity adopts a regenerated identity or credential set while the Node keeps
// running.
//
// This is what makes `connector-node regenerate` mean what the design says it means.
// Regeneration is a separate process that rewrites the identity file and exits;
// without a watcher the running Node would keep serving the identifier it read at
// startup, so the old address would keep working and the new one would be refused.
//
// The credential file is watched for the same reason, and the two are watched
// separately because they answer different questions. A regenerated identifier drops
// the live channel, because the channel was authenticated with a name that no longer
// exists. A changed credential set does not drop the channel: the channel was
// authenticated with the tunnel token, which is a different secret, and dropping a
// working channel because an operator revoked an unrelated caller would be a
// self-inflicted outage.
//
// The comparison is on the values, not on the files' modification times or sizes.
// Both of those are unreliable here: a regenerated identifier has exactly the same
// byte length as the one it replaces, and a rewrite can land inside the same
// modification-time tick as the read that produced the current value. A stamp
// comparison therefore reports "unchanged" for a file that holds a different value,
// which is the one case this function exists to notice.
//
// A file that cannot be read is logged once and skipped, and the previous value stays
// in force. Adopting a half-written or malformed file would leave the Node serving a
// value it cannot parse, which is worse than serving the old one until the operator
// fixes the file. The warning is logged once per distinct problem rather than once
// per poll, because a poll that repeats the same warning every second buries the
// first occurrence.
func (d *Dialer) watchIdentity(ctx context.Context, changes chan<- struct{}) {
	if d.identityPath == "" && d.credentialsPath == "" {
		return
	}

	ticker := time.NewTicker(identityPollInterval)
	defer ticker.Stop()

	// lastProblem suppresses a repeated warning. An empty value means the last poll
	// found nothing to report.
	lastProblem := ""

	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
		}

		problem := d.pollIdentity()
		if problem != "" {
			if problem != lastProblem {
				lastProblem = problem
				d.logger.Warn("identity or credential file could not be read; keeping the value in force",
					"node_id", d.holder.NodeID(),
					"problem", problem,
				)
			}
			continue
		}
		lastProblem = ""

		if d.identityChanged {
			d.identityChanged = false
			d.logger.Info("identity file changed; adopting the new node id and dropping the channel",
				"node_id", d.holder.NodeID(),
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
}

// pollIdentity reads both files and adopts whatever changed.
//
// It returns a stable description of the first problem it found, or an empty string
// when both files were read. The description is not the error text, because the text
// embeds a file path and a wrapped error whose text varied per poll would defeat the
// suppression it is meant to drive.
func (d *Dialer) pollIdentity() string {
	if d.identityPath != "" {
		nodeID, err := LoadIdentity(d.identityPath)
		if err != nil {
			return describeIdentityProblem(err)
		}
		if d.holder.ReplaceNodeID(nodeID) {
			d.identityChanged = true
		}
	}

	if d.credentialsPath != "" {
		credentials, err := LoadCredentials(d.credentialsPath)
		if err != nil {
			return describeCredentialProblem(err)
		}
		if d.holder.ReplaceCredentials(credentials) {
			d.logger.Info("credential file changed; adopting the new credential set",
				"node_id", d.holder.NodeID(),
				"client_key_ids", credentials.KeyIDs(),
			)
		}
	}

	return ""
}

// describeIdentityProblem reduces an identity load failure to a stable description.
func describeIdentityProblem(err error) string {
	if errors.Is(err, ErrIdentityMissing) {
		return "identity missing"
	}
	return "identity malformed"
}

// describeCredentialProblem reduces a credential load failure to a stable
// description.
func describeCredentialProblem(err error) string {
	if errors.Is(err, ErrCredentialsMissing) {
		return "credentials missing"
	}
	return "credentials malformed"
}

// discardPendingIdentityChange removes a change signal that arrived while no channel
// was live.
//
// Without this, a regeneration during a reconnect delay would leave a signal in the
// buffer, and the next loop iteration would drop the freshly established channel even
// though it was authenticated with the new identity.
func discardPendingIdentityChange(changes <-chan struct{}) {
	select {
	case <-changes:
	default:
	}
}

// identityChangeContext derives a context that is cancelled when the identity
// changes, so one channel is dropped without ending the reconnect loop.
//
// The returned stop function must be called when the connection ends, otherwise the
// goroutine outlives the connection it was installed for.
func identityChangeContext(ctx context.Context, changes <-chan struct{}) (context.Context, context.CancelFunc) {
	changeCtx, cancel := context.WithCancel(ctx)
	if changes == nil {
		return changeCtx, cancel
	}

	// done releases the goroutine when the connection ends for another reason, so a
	// connection that closes normally does not leave a goroutine waiting on a signal
	// that will never arrive.
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
