// Package supervisor runs one task round under the task's lock.
//
// The scheduler is a process supervisor, not a judge. It starts a run, watches
// the run's lifecycle, and stops watching when the run ends. It never decides
// whether the work succeeded: the success criteria belong to the task's Markdown
// content, which the provider reads.
//
// The lock spans the whole supervision, not just the provider's start call. A
// provider returns a handle promptly and does the work in the background, so a
// lock released when Start returned would be free while the run was still
// working, and the next tick could start a second copy of the same task. Holding
// the lock until the run reports finished makes the lock mean "this task has a
// round under supervision", which is the only meaning that prevents overlap.
package supervisor

import (
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"os"
	"time"

	"topsailai_scheduler/lock"
	"topsailai_scheduler/provider"
)

// DefaultPollInterval is how often a run's state is checked when no interval is
// configured. A protocol call is a short exchange, so a few seconds is enough to
// notice that a run ended without keeping the provider busy answering.
const DefaultPollInterval = 5 * time.Second

// StopTimeout bounds the stop call made when supervision ends early. It is short
// because a provider must answer a protocol call promptly.
const StopTimeout = 30 * time.Second

// Outcome is the result of one supervised round.
type Outcome struct {
	// Skipped is true when another round already held the lock, so nothing was
	// started.
	Skipped bool
	// Handle is the run identity the provider returned.
	Handle provider.Handle
	// State is the last state the provider reported.
	State provider.State
	// ExitCode is the run's exit status when the provider reported one. It is a
	// lifecycle fact, not a verdict.
	ExitCode int
	// Detail is the provider's free-form text for the last observation.
	Detail string
	// StartedAt is when supervision began.
	StartedAt time.Time
	// FinishedAt is when supervision ended.
	FinishedAt time.Time
	// TimedOut is true when the round ended because its timeout elapsed.
	TimedOut bool
	// Canceled is true when the round ended because the caller's context ended.
	Canceled bool
	// Polls is how many times the provider was asked for the state.
	Polls int
	// Reconciled is true when the lock file carried a record from a previous
	// supervisor, so a run left behind was checked before this round started.
	Reconciled bool
	// ReconciledState is the state the provider reported for that recorded run.
	// It is empty when no record was found.
	ReconciledState provider.State
	// Err is the failure that ended supervision early, if any.
	Err error
}

// Options configures one supervised round.
type Options struct {
	// Provider starts, observes and stops the run.
	Provider provider.Provider
	// Request describes the run to start.
	Request provider.Request
	// LockPath is the task's lock file.
	LockPath string
	// PollInterval is how often the run's state is checked. Zero means
	// DefaultPollInterval.
	PollInterval time.Duration
	// Timeout bounds the whole round. Zero means no timeout.
	Timeout time.Duration
	// Logger receives supervision events. Nil discards them.
	Logger *slog.Logger
	// OnStart is called once the run has a handle, before the first poll.
	OnStart func(provider.Handle)
	// OnObservation is called after every successful poll.
	OnObservation func(provider.Observation)
}

// Run supervises one round: take the lock, start the run, poll until it ends,
// then release the lock.
//
// The lock is released when Run returns, which is after the run ended, not after
// the provider's start call returned. That is what makes the lock mean "this task
// has a round under supervision" and prevents a second copy from starting while
// the first is still working.
func Run(ctx context.Context, options Options) Outcome {
	outcome := Outcome{StartedAt: time.Now()}
	logger := options.Logger
	if logger == nil {
		logger = slog.New(slog.NewTextHandler(io.Discard, nil))
	}

	if options.Provider == nil {
		outcome.Err = fmt.Errorf("supervise run: no provider")
		outcome.FinishedAt = time.Now()
		return outcome
	}
	if options.LockPath == "" {
		outcome.Err = fmt.Errorf("supervise run: no lock path")
		outcome.FinishedAt = time.Now()
		return outcome
	}

	held, acquired, acquireErr := lock.TryAcquire(options.LockPath)
	if acquireErr != nil {
		outcome.Err = fmt.Errorf("acquire lock %s: %w", options.LockPath, acquireErr)
		outcome.FinishedAt = time.Now()
		return outcome
	}
	if !acquired {
		outcome.Skipped = true
		outcome.FinishedAt = time.Now()
		return outcome
	}
	// Releasing here, and not after Start, is the whole point: the lock must
	// outlive the start call for as long as the run is alive.
	defer func() {
		if releaseErr := held.Release(); releaseErr != nil {
			logger.Error("lock release failed",
				slog.String("lock", options.LockPath),
				slog.String("error", releaseErr.Error()),
			)
		}
	}()

	// A record left by a previous supervisor names a run that may still be
	// working, because a run outlives the scheduler that started it. Starting a
	// new run without checking would duplicate the work, so the record is
	// reconciled before anything is started.
	previous, reconcileErr := reconcile(ctx, options.Provider, held, logger)
	outcome.Reconciled = previous.Found
	outcome.ReconciledState = previous.State
	if reconcileErr != nil {
		outcome.Err = reconcileErr
		outcome.FinishedAt = time.Now()
		return outcome
	}
	if previous.Busy {
		outcome.Skipped = true
		outcome.FinishedAt = time.Now()
		return outcome
	}

	handle, startErr := options.Provider.Start(ctx, options.Request)
	if startErr != nil {
		outcome.Err = fmt.Errorf("start run: %w", startErr)
		outcome.FinishedAt = time.Now()
		return outcome
	}
	outcome.Handle = handle
	if options.OnStart != nil {
		options.OnStart(handle)
	}

	// The record is written once the run has an identity, so a supervisor that
	// dies during supervision leaves behind exactly what the next start needs to
	// check. A failure here weakens restart reconciliation but does not affect
	// supervision of the run that is already going, so it is logged, not fatal.
	record := lock.Record{
		RunID:        handle.ID,
		Provider:     handle.Provider,
		PID:          handle.PID,
		StartedAt:    handle.StartedAt,
		SchedulerPID: os.Getpid(),
	}
	if recordErr := held.WriteRecord(record); recordErr != nil {
		logger.Warn("lock record write failed",
			slog.String("run_id", handle.ID),
			slog.String("error", recordErr.Error()),
		)
	}

	runCtx := ctx
	if options.Timeout > 0 {
		var cancel context.CancelFunc
		runCtx, cancel = context.WithTimeout(ctx, options.Timeout)
		defer cancel()
	}

	interval := options.PollInterval
	if interval <= 0 {
		interval = DefaultPollInterval
	}
	ticker := time.NewTicker(interval)
	defer ticker.Stop()

	for {
		select {
		case <-runCtx.Done():
			outcome.TimedOut = errors.Is(runCtx.Err(), context.DeadlineExceeded)
			outcome.Canceled = !outcome.TimedOut
			stopRun(options.Provider, handle, logger)
			outcome.FinishedAt = time.Now()
			return outcome
		case <-ticker.C:
			observation, pollErr := options.Provider.Poll(runCtx, handle)
			outcome.Polls++
			if pollErr != nil {
				// A failed poll is not evidence that the run ended. Reporting it
				// as finished would abandon a run that may still be working, so
				// supervision continues and the timeout bounds it.
				logger.Warn("poll failed, run state unknown",
					slog.String("run_id", handle.ID),
					slog.String("error", pollErr.Error()),
				)
				continue
			}
			outcome.State = observation.State
			outcome.ExitCode = observation.ExitCode
			outcome.Detail = observation.Detail
			if options.OnObservation != nil {
				options.OnObservation(observation)
			}
			if observation.State == provider.StateFinished {
				// The run is confirmed ended, so the breadcrumb is no longer
				// needed. Clearing it keeps the next start from reconciling a
				// run that is already over. A timeout or a cancel does not
				// clear it: the run was only asked to stop, and the next start
				// must still check whether it obeyed.
				if clearErr := held.ClearRecord(); clearErr != nil {
					logger.Warn("lock record clear failed",
						slog.String("run_id", handle.ID),
						slog.String("error", clearErr.Error()),
					)
				}
				outcome.FinishedAt = time.Now()
				return outcome
			}
		}
	}
}

// stopRun asks the provider to end the run, bounded by StopTimeout.
//
// The stop call uses a fresh context: the caller's context is already done, and
// reusing it would cancel the stop request before the provider could act on it.
func stopRun(implementation provider.Provider, handle provider.Handle, logger *slog.Logger) {
	stopCtx, cancel := context.WithTimeout(context.Background(), StopTimeout)
	defer cancel()
	if stopErr := implementation.Stop(stopCtx, handle); stopErr != nil {
		logger.Error("stop run failed",
			slog.String("run_id", handle.ID),
			slog.String("error", stopErr.Error()),
		)
	}
}

// reconciliation is what a stale lock record turned out to mean.
type reconciliation struct {
	// Found is true when the lock file carried a usable record.
	Found bool
	// Busy is true when the recorded run is still alive, so this round must not
	// start another one.
	Busy bool
	// State is the state the provider reported for the recorded run.
	State provider.State
}

// reconcile checks the run named by a stale lock record before a new one starts.
//
// A run is a separate process that outlives the scheduler, so after a restart the
// lock is free while the run may still be working. The record is the only thing
// that names it. Three outcomes are possible:
//
//   - no record: nothing to reconcile, so the round proceeds;
//   - the run is finished: the record is stale, so it is cleared and the round
//     proceeds;
//   - the run is running or unknown: the round is skipped, because starting a
//     second copy is the failure this whole mechanism exists to prevent.
//
// An unknown state is treated as busy on purpose. A provider that cannot answer
// is not evidence that the run ended, and the cost of waiting one more tick is a
// delayed run, while the cost of guessing wrong is duplicated work.
func reconcile(ctx context.Context, implementation provider.Provider, held *lock.Lock, logger *slog.Logger) (reconciliation, error) {
	record, readErr := lock.ReadRecord(held.Path())
	if readErr != nil {
		return reconciliation{}, fmt.Errorf("read lock record %s: %w", held.Path(), readErr)
	}
	if record.IsZero() {
		return reconciliation{}, nil
	}

	// The record names the provider that owns the run. Asking a different one
	// would be meaningless, so a mismatch is reported rather than guessed at.
	if record.Provider != "" && record.Provider != implementation.Name() {
		return reconciliation{}, fmt.Errorf(
			"lock record %s names provider %q but this task now uses %q: the recorded run cannot be checked",
			held.Path(), record.Provider, implementation.Name())
	}

	logger.Info("reconciling a run left by a previous supervisor",
		slog.String("run_id", record.RunID),
		slog.String("provider", record.Provider),
		slog.Int("pid", record.PID),
		slog.Int("scheduler_pid", record.SchedulerPID),
	)

	handle := provider.Handle{
		Provider:  record.Provider,
		ID:        record.RunID,
		PID:       record.PID,
		StartedAt: record.StartedAt,
	}
	observation, pollErr := implementation.Poll(ctx, handle)
	if pollErr != nil {
		// A failed poll cannot prove the run ended, so the round is skipped and
		// the record is left in place for the next attempt.
		logger.Warn("reconcile poll failed, treating the run as still busy",
			slog.String("run_id", record.RunID),
			slog.String("error", pollErr.Error()),
		)
		return reconciliation{Found: true, Busy: true}, nil
	}

	result := reconciliation{Found: true, State: observation.State}
	switch observation.State {
	case provider.StateFinished:
		// The recorded run is over, so the record is stale. Clearing it lets
		// this round start normally.
		if clearErr := held.ClearRecord(); clearErr != nil {
			return reconciliation{}, fmt.Errorf("clear stale lock record %s: %w", held.Path(), clearErr)
		}
		logger.Info("the recorded run already finished, starting a new one",
			slog.String("run_id", record.RunID),
		)
		return result, nil
	case provider.StateRunning, provider.StateUnknown:
		result.Busy = true
		logger.Info("the recorded run is still in flight, skipping this round",
			slog.String("run_id", record.RunID),
			slog.String("state", string(observation.State)),
		)
		return result, nil
	default:
		return reconciliation{}, fmt.Errorf("reconcile run %q: unexpected state %q",
			record.RunID, observation.State)
	}
}
