// Package daemon runs the scheduler loop and implements the runtime control
// contract.
//
// The daemon owns one cron instance, registers every discovered task with it,
// and periodically rescans the task source so adding or removing task files
// takes effect without a restart. Each due task is handed to a bounded worker
// pool, so a slow task cannot starve the others and the process never blocks on
// a single run.
//
// Launch, Status and Stop are the standardized control operations. A transport
// such as the control socket only decodes a request and calls them, so every
// transport behaves identically.
package daemon

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"sort"
	"strings"
	"sync"
	"time"

	"github.com/robfig/cron/v3"

	"topsailai_scheduler/config"
	"topsailai_scheduler/launcher"
	"topsailai_scheduler/lock"
	"topsailai_scheduler/logging"
	"topsailai_scheduler/provider"
	"topsailai_scheduler/runtime"
	"topsailai_scheduler/supervisor"
	"topsailai_scheduler/task"
)

// historySize is how many completed runs are remembered per task for Status.
const historySize = 5

// Daemon is the running scheduler.
type Daemon struct {
	cfg       config.Config
	logger    *slog.Logger
	cron      *cron.Cron
	launchers *launcher.Registry
	providers *provider.Resolver
	// providerPath is the absolute default provider executable, resolved once at
	// startup so the log and every task agree on one value.
	providerPath string
	source       task.Source

	// mu guards the task bookkeeping below.
	mu sync.Mutex
	// entries maps a task id to its cron entry and fingerprint.
	entries map[string]registered
	// tasks holds the last loaded task per id, including disabled ones.
	tasks map[string]task.Task
	// runs holds the in-flight run per task id.
	runs map[string]*activeRun
	// history holds the most recent completed runs per task id.
	history map[string][]runtime.RunRecord
	// failures remembers the last reported load error per path so an unchanged
	// broken file is not logged on every rescan.
	failures map[string]string
	// providerFailures remembers the last reported provider error per task id, so
	// a task naming a missing provider is logged once instead of on every rescan.
	// It is keyed by task id rather than by file path because the file itself is
	// readable; what is broken is the provider it names.
	providerFailures map[string]string
	// stopping is true once shutdown began; new launches are refused.
	stopping bool

	// slots bounds how many runs execute at the same time.
	slots chan struct{}
	// workers tracks in-flight runs so shutdown can wait for them.
	workers sync.WaitGroup
	// baseContext is the parent of every run context, cancelled on shutdown.
	baseContext context.Context
	// cancelBase cancels baseContext.
	cancelBase context.CancelFunc
}

// registered is one scheduled task.
type registered struct {
	// entryID is the cron entry id, used to remove the schedule.
	entryID cron.EntryID
	// fingerprint is the task content hash at registration time.
	fingerprint string
}

// activeRun is one in-flight run.
type activeRun struct {
	// info is the reported run state.
	info runtime.RunInfo
	// cancel stops the run context.
	cancel context.CancelFunc
	// stopped records that the run was stopped through the contract.
	stopped bool
	// skipped records that the round never started because another round held
	// the task lock.
	skipped bool
	// done is closed when the run finishes.
	done chan struct{}
	// record is the completed run, valid after done is closed.
	record runtime.RunRecord
	// handle is the provider's run identity, set once the provider reports it.
	handle provider.Handle
	// implementation is the provider supervising this run.
	implementation provider.Provider
	// onStart is called by the supervisor once the run has a handle.
	onStart func(provider.Handle)
}

// New builds a daemon from the configuration.
//
// The task source, launcher registry and provider resolver are injected so all
// three are replaceable: a different discovery mechanism, a new launcher or a
// different provider executable needs no change here.
//
// providerPath is the absolute default provider executable. It is resolved by
// the caller, which is also where the requirement is enforced, so a daemon can
// never be built without a provider to run tasks with.
func New(cfg config.Config, logger *slog.Logger, source task.Source, launchers *launcher.Registry, providers *provider.Resolver, providerPath string) *Daemon {
	baseContext, cancelBase := context.WithCancel(context.Background())
	return &Daemon{
		cfg:              cfg,
		logger:           logging.Module(logger, "daemon"),
		cron:             cron.New(cron.WithSeconds(), cron.WithChain(cron.SkipIfStillRunning(cron.DiscardLogger))),
		launchers:        launchers,
		providers:        providers,
		providerPath:     providerPath,
		source:           source,
		entries:          make(map[string]registered),
		tasks:            make(map[string]task.Task),
		runs:             make(map[string]*activeRun),
		history:          make(map[string][]runtime.RunRecord),
		failures:         make(map[string]string),
		providerFailures: make(map[string]string),
		slots:            make(chan struct{}, cfg.MaxConcurrent),
		baseContext:      baseContext,
		cancelBase:       cancelBase,
	}
}

// Run starts the scheduler and blocks until ctx ends.
//
// On shutdown the cron stops accepting new triggers, running tasks are allowed
// to finish within the grace period, and only then is the process released.
func (d *Daemon) Run(ctx context.Context) error {
	root, err := d.cfg.AbsoluteTasksRoot()
	if err != nil {
		return err
	}

	d.logger.Info("scheduler starting",
		slog.String("tasks_root", root),
		slog.Int("max_concurrent", d.cfg.MaxConcurrent),
		slog.Duration("rescan_interval", d.cfg.RescanInterval),
		slog.String("default_provider_path", d.providerPath),
		slog.Any("launchers", d.launchers.Names()),
	)

	if err := d.rescan(); err != nil {
		return err
	}
	d.cron.Start()

	rescanTicker := time.NewTicker(d.cfg.RescanInterval)
	defer rescanTicker.Stop()

	for {
		select {
		case <-ctx.Done():
			d.shutdown()
			return nil
		case <-rescanTicker.C:
			if err := d.rescan(); err != nil {
				d.logger.Error("rescan failed", slog.String("error", err.Error()))
			}
		}
	}
}

// shutdown stops scheduling and waits for in-flight runs.
func (d *Daemon) shutdown() {
	d.logger.Info("scheduler stopping", slog.Duration("grace", d.cfg.ShutdownGrace))

	d.mu.Lock()
	d.stopping = true
	d.mu.Unlock()

	// Stop the cron first so no new run starts while we are draining.
	stopContext := d.cron.Stop()
	select {
	case <-stopContext.Done():
	case <-time.After(d.cfg.ShutdownGrace):
		d.logger.Warn("cron did not drain within the grace period")
	}

	drained := make(chan struct{})
	go func() {
		d.workers.Wait()
		close(drained)
	}()

	select {
	case <-drained:
		d.logger.Info("all running tasks finished")
	case <-time.After(d.cfg.ShutdownGrace):
		// Cancel the run contexts so the remaining children are terminated
		// together with their process groups instead of being orphaned.
		d.logger.Warn("grace period expired, terminating running tasks")
		d.cancelBase()
		<-drained
	}

	d.logger.Info("scheduler stopped")
}

// rescan reloads the task source and reconciles the cron entries.
func (d *Daemon) rescan() error {
	loaded, failures, err := d.source.Load()
	if err != nil {
		return err
	}
	d.reportFailures(failures)

	desired := make(map[string]task.Task, len(loaded))
	providerErrors := make(map[string]string, len(loaded))
	for _, item := range loaded {
		if !item.Spec.IsEnabled() {
			d.logger.Debug("task disabled", slog.String("task", item.ID))
			continue
		}
		// A task whose provider executable is missing cannot run, so it is
		// rejected here rather than scheduled and skipped on every trigger. The
		// task stays in d.tasks, so a launch still reports the real reason
		// instead of claiming the task does not exist.
		if _, checkErr := d.providers.Check(d.providerPathFor(item)); checkErr != nil {
			providerErrors[item.ID] = checkErr.Error()
			continue
		}
		desired[item.ID] = item
	}
	d.reportProviderFailures(providerErrors)

	d.mu.Lock()
	defer d.mu.Unlock()

	d.tasks = make(map[string]task.Task, len(loaded))
	for _, item := range loaded {
		d.tasks[item.ID] = item
	}

	// Remove tasks that disappeared or whose content changed.
	for id, current := range d.entries {
		wanted, stillPresent := desired[id]
		if stillPresent && wanted.Fingerprint == current.fingerprint {
			continue
		}
		d.cron.Remove(current.entryID)
		delete(d.entries, id)
		if stillPresent {
			d.logger.Info("task changed, rescheduling", slog.String("task", id))
		} else {
			d.logger.Info("task removed", slog.String("task", id))
		}
	}

	// Register new tasks. A task whose schedule cannot be parsed is reported and
	// skipped; it must not abort the whole scan.
	for id, item := range desired {
		if _, exists := d.entries[id]; exists {
			continue
		}
		entryID, err := d.schedule(item)
		if err != nil {
			d.logger.Error("task not scheduled",
				slog.String("task", id),
				slog.String("path", item.YAMLPath),
				slog.String("error", err.Error()),
			)
			continue
		}
		d.entries[id] = registered{entryID: entryID, fingerprint: item.Fingerprint}
		d.logger.Info("task scheduled",
			slog.String("task", id),
			slog.String("schedule", item.Spec.Schedule),
			slog.String("launcher", d.launcherName(item)),
			slog.String("provider", d.providerPathFor(item)),
			slog.String("path", item.YAMLPath),
		)
	}

	return nil
}

// schedule registers one task with the cron and returns its entry id.
func (d *Daemon) schedule(item task.Task) (cron.EntryID, error) {
	expression := strings.TrimSpace(item.Spec.Schedule)
	// A five-field expression is the familiar cron form. The cron instance is
	// created with seconds enabled, so a five-field expression is prefixed with
	// a zero second field rather than rejected.
	if len(strings.Fields(expression)) == 5 {
		expression = "0 " + expression
	}

	entryID, err := d.cron.AddFunc(expression, func() {
		d.trigger(item)
	})
	if err != nil {
		return 0, fmt.Errorf("invalid schedule %q: %w", item.Spec.Schedule, err)
	}
	return entryID, nil
}

// trigger starts one run of a task in the background.
//
// The cron callback must return quickly: waiting for the run would block every
// other task scheduled at the same moment.
func (d *Daemon) trigger(item task.Task) {
	if _, err := d.start(item, false); err != nil {
		d.logger.Info("scheduled run skipped",
			slog.String("task", item.ID),
			slog.String("reason", err.Error()),
		)
	}
}

// start launches one run and returns once the provider has a handle for it.
func (d *Daemon) start(item task.Task, wait bool) (runtime.LaunchResult, error) {
	request, launcherName, providerName, err := d.buildRequest(item)
	if err != nil {
		return runtime.LaunchResult{}, err
	}

	implementation, err := d.providers.Provider(providerName)
	if err != nil {
		return runtime.LaunchResult{}, err
	}

	traceID := newTraceID(item.ID)
	runContext, cancelRun := context.WithCancel(d.baseContext)

	started := make(chan provider.Handle, 1)
	run := &activeRun{
		info: runtime.RunInfo{
			StartedAt: time.Now(),
			TraceID:   traceID,
			Launcher:  launcherName,
			Provider:  providerName,
			Command:   request.Command,
		},
		cancel:         cancelRun,
		done:           make(chan struct{}),
		implementation: implementation,
	}
	// The callback is assigned after the struct exists so it can update the run
	// it belongs to.
	run.onStart = func(handle provider.Handle) {
		d.mu.Lock()
		run.info.PID = handle.PID
		run.info.RunID = handle.ID
		run.handle = handle
		d.mu.Unlock()
		started <- handle
	}

	d.mu.Lock()
	if d.stopping {
		d.mu.Unlock()
		cancelRun()
		return runtime.LaunchResult{}, runtime.ErrShuttingDown
	}
	if _, busy := d.runs[item.ID]; busy {
		d.mu.Unlock()
		cancelRun()
		// A still-running instance owns the task. Skipping is correct: the next
		// tick will try again, and queueing would only pile up runs.
		return runtime.LaunchResult{TaskID: item.ID, Skipped: true}, nil
	}
	d.runs[item.ID] = run
	d.mu.Unlock()

	d.workers.Add(1)
	go func() {
		defer d.workers.Done()
		defer cancelRun()
		defer close(run.done)
		d.execute(runContext, item, request, launcherName, providerName, traceID, run)
	}()

	select {
	case handle := <-started:
		result := runtime.LaunchResult{TaskID: item.ID, PID: handle.PID, TraceID: traceID}
		if wait {
			<-run.done
			record := run.record
			result.Record = &record
		}
		return result, nil
	case <-run.done:
		// The round ended before the provider produced a handle, which means it
		// was skipped or failed to start. Report the recorded outcome instead of
		// a pid.
		record := run.record
		return runtime.LaunchResult{
			TaskID:  item.ID,
			TraceID: traceID,
			Skipped: run.skipped,
			Record:  &record,
		}, nil
	}
}

// execute supervises one round: take the lock, start the run, poll until it
// ends, then release the lock.
//
// The lock is owned by the supervisor, not by this function, so it spans the
// whole round rather than only the provider's start call. That is what stops a
// second copy of the same task from starting while the first is still working.
//
// Nothing here decides whether the work succeeded. The provider reports whether
// the run is alive, and the task's Markdown content defines what success means.
func (d *Daemon) execute(ctx context.Context, item task.Task, request provider.Request, launcherName, providerName, traceID string, run *activeRun) {
	logger := logging.WithTrace(d.logger, traceID).With(slog.String("task", item.ID))

	select {
	case d.slots <- struct{}{}:
		defer func() { <-d.slots }()
	case <-ctx.Done():
		logger.Info("run skipped, scheduler stopping")
		d.finish(item.ID, run, runtime.RunRecord{
			StartedAt:  run.info.StartedAt,
			FinishedAt: time.Now(),
			ExitCode:   -1,
			TraceID:    traceID,
			Launcher:   launcherName,
			Provider:   providerName,
		})
		return
	}

	logger.Info("run starting",
		slog.String("launcher", launcherName),
		slog.String("provider", providerName),
		slog.String("command", request.Command),
		slog.String("workspace", request.Workspace),
		slog.Duration("timeout", request.Timeout),
	)

	outcome := supervisor.Run(ctx, supervisor.Options{
		Provider:     run.implementation,
		Request:      request,
		LockPath:     item.LockPath,
		PollInterval: d.cfg.PollInterval,
		Timeout:      request.Timeout,
		Logger:       logger,
		OnStart:      run.onStart,
	})

	d.mu.Lock()
	stopped := run.stopped
	d.mu.Unlock()

	// A round that never started has no exit status, so -1 marks "unknown"
	// rather than inventing a zero that would read like a clean exit.
	exitCode := outcome.ExitCode
	if outcome.Skipped || outcome.Err != nil {
		exitCode = -1
	}

	record := runtime.RunRecord{
		StartedAt:  outcome.StartedAt,
		FinishedAt: outcome.FinishedAt,
		ExitCode:   exitCode,
		TimedOut:   outcome.TimedOut,
		Stopped:    stopped,
		TraceID:    traceID,
		Launcher:   launcherName,
		Provider:   providerName,
		RunID:      outcome.Handle.ID,
		State:      string(outcome.State),
	}

	attributes := []any{
		slog.String("provider", providerName),
		slog.String("run_id", outcome.Handle.ID),
		slog.String("state", string(outcome.State)),
		slog.Int("exit_code", exitCode),
		slog.Int("polls", outcome.Polls),
		slog.Duration("duration", outcome.FinishedAt.Sub(outcome.StartedAt)),
		slog.Bool("timed_out", outcome.TimedOut),
		slog.Bool("canceled", outcome.Canceled),
		slog.Bool("stopped", stopped),
	}
	if outcome.Reconciled {
		attributes = append(attributes,
			slog.Bool("reconciled", true),
			slog.String("reconciled_state", string(outcome.ReconciledState)),
		)
	}
	if outcome.Detail != "" {
		attributes = append(attributes, slog.String("detail", outcome.Detail))
	}
	if outcome.Err != nil {
		attributes = append(attributes, slog.String("error", outcome.Err.Error()))
	}

	// These messages describe the lifecycle only. The exit code is logged as a
	// fact, never as a verdict: whether the work was good is the task content's
	// business, not the scheduler's.
	switch {
	case outcome.Skipped:
		run.skipped = true
		// A skip has two distinct causes and they must not read alike: another
		// round holding the lock is routine, while a run left in flight by a
		// dead supervisor means work is still going on from before the restart.
		if outcome.Reconciled {
			logger.Info("run skipped, a run from a previous supervisor is still in flight",
				slog.String("lock", item.LockPath),
				slog.String("reconciled_state", string(outcome.ReconciledState)),
			)
		} else {
			logger.Info("run skipped, task already running", slog.String("lock", item.LockPath))
		}
	case stopped:
		logger.Warn("run stopped by request", attributes...)
	case outcome.TimedOut:
		logger.Error("run timed out", attributes...)
	case outcome.Canceled:
		logger.Warn("run canceled", attributes...)
	case outcome.Err != nil:
		logger.Error("run failed to execute", attributes...)
	default:
		logger.Info("run finished", attributes...)
	}

	d.finish(item.ID, run, record)
}

// finish records a completed run and clears the in-flight entry.
func (d *Daemon) finish(taskID string, run *activeRun, record runtime.RunRecord) {
	d.mu.Lock()
	defer d.mu.Unlock()

	run.record = record
	if current, exists := d.runs[taskID]; exists && current == run {
		delete(d.runs, taskID)
	}

	records := append(d.history[taskID], record)
	if len(records) > historySize {
		records = records[len(records)-historySize:]
	}
	d.history[taskID] = records
}

// buildRequest turns a task into a provider request through its launcher.
//
// The launcher and the provider are resolved separately because they answer
// different questions: the launcher describes the run, the provider performs it.
// A task may therefore use the same launcher with a different provider.
func (d *Daemon) buildRequest(item task.Task) (provider.Request, string, string, error) {
	launcherName := d.launcherName(item)
	implementation, err := d.launchers.Get(launcherName)
	if err != nil {
		return provider.Request{}, launcherName, "", err
	}

	providerPath := d.providerPathFor(item)
	if _, providerErr := d.providers.Executable(providerPath); providerErr != nil {
		return provider.Request{}, launcherName, providerPath, providerErr
	}

	defaults := launcher.Defaults{
		Workspace: d.cfg.Workspace,
		Timeout:   d.cfg.DefaultTimeout,
	}

	request, err := implementation.Build(item, defaults)
	if err != nil {
		return provider.Request{}, launcherName, providerPath, fmt.Errorf("build run for task %q: %w", item.ID, err)
	}
	return request, launcherName, providerPath, nil
}

// launcherName returns the launcher a task selects, defaulting to the agent.
func (d *Daemon) launcherName(item task.Task) string {
	name := strings.TrimSpace(item.Spec.Launcher)
	if name == "" {
		return launcher.NameAgent
	}
	return name
}

// providerPathFor returns the provider executable a task selects, defaulting to
// the configured one.
//
// The default lives in configuration rather than in the task, so switching the
// provider for a whole installation does not require editing every task file.
// The value is a path, so a task may point at a provider anywhere on disk
// instead of being limited to a folder the scheduler knows about.
//
// The path is resolved to an absolute one here, so the provider identity is the
// same string everywhere: the startup log, the lock record and the reconciliation
// comparison all see one form. A path that cannot be resolved is returned as
// written; the resolver then reports it with the location it looked for.
func (d *Daemon) providerPathFor(item task.Task) string {
	path := strings.TrimSpace(item.Spec.Provider)
	if path == "" {
		return d.providerPath
	}
	absolute, err := d.providers.Executable(path)
	if err != nil {
		return path
	}
	return absolute
}

// reportFailures logs load errors, suppressing repeats of an unchanged failure.
func (d *Daemon) reportFailures(failures []task.LoadError) {
	seen := make(map[string]string, len(failures))
	for _, failure := range failures {
		message := failure.Err.Error()
		seen[failure.Path] = message
		if previous, known := d.failures[failure.Path]; known && previous == message {
			continue
		}
		d.logger.Error("task file rejected",
			slog.String("path", failure.Path),
			slog.String("error", message),
		)
	}

	// A file that loads again is reported once so a fixed task is visible.
	for path := range d.failures {
		if _, stillFailing := seen[path]; !stillFailing {
			d.logger.Info("task file recovered", slog.String("path", path))
		}
	}
	d.failures = seen
}

// reportProviderFailures logs a task whose provider executable is unusable once
// per distinct message, and logs recovery when the provider becomes usable
// again.
//
// The once-per-message rule matters because the task tree is rescanned on a
// timer: a provider that stays missing would otherwise write the same error on
// every scan. It mirrors reportFailures so both kinds of rejection behave the
// same way.
func (d *Daemon) reportProviderFailures(failures map[string]string) {
	for id, message := range failures {
		if previous, known := d.providerFailures[id]; known && previous == message {
			continue
		}
		d.logger.Error("task not scheduled",
			slog.String("task", id),
			slog.String("error", message),
		)
	}

	// A task whose provider is back is reported once so the recovery is visible.
	for id := range d.providerFailures {
		if _, stillFailing := failures[id]; !stillFailing {
			d.logger.Info("task provider recovered", slog.String("task", id))
		}
	}
	d.providerFailures = failures
}

// Launch starts one run of a task now.
//
// It implements runtime.Controller. A disabled task is refused rather than run,
// because running it would contradict its own configuration.
func (d *Daemon) Launch(request runtime.LaunchRequest) (runtime.LaunchResult, error) {
	item, err := d.taskByID(request.TaskID)
	if err != nil {
		return runtime.LaunchResult{}, err
	}
	if !item.Spec.IsEnabled() {
		return runtime.LaunchResult{}, fmt.Errorf("%w: %s", runtime.ErrTaskDisabled, request.TaskID)
	}
	return d.start(item, request.Wait)
}

// Status reports the current state of every task.
//
// It implements runtime.Controller.
func (d *Daemon) Status() (runtime.Snapshot, error) {
	root, err := d.cfg.AbsoluteTasksRoot()
	if err != nil {
		return runtime.Snapshot{}, err
	}

	d.mu.Lock()
	defer d.mu.Unlock()

	statuses := make([]runtime.TaskStatus, 0, len(d.tasks))
	for id, item := range d.tasks {
		status := runtime.TaskStatus{
			ID:           id,
			Schedule:     item.Spec.Schedule,
			Launcher:     d.launcherName(item),
			Provider:     d.providerPathFor(item),
			YAMLPath:     item.YAMLPath,
			MarkdownPath: item.MarkdownPath,
			State:        runtime.StateIdle,
		}
		if !item.Spec.IsEnabled() {
			status.State = runtime.StateDisabled
		}
		// A task whose provider is unusable is reported as invalid so the
		// reason is visible through Status, not only in the log. The running
		// check below still wins: a live process must not be hidden as
		// invalid just because its provider was removed mid-run.
		if message, broken := d.providerFailures[id]; broken {
			status.State = runtime.StateInvalid
			status.Error = message
		}
		if entry, scheduled := d.entries[id]; scheduled {
			status.NextRun = d.cron.Entry(entry.entryID).Next
		}
		if run, running := d.runs[id]; running {
			status.State = runtime.StateRunning
			info := run.info
			status.Run = &info
		}
		if records := d.history[id]; len(records) > 0 {
			last := records[len(records)-1]
			status.LastRun = &last
		}
		statuses = append(statuses, status)
	}

	// A rejected file is reported as an invalid task so a broken task is visible
	// through Status instead of only in the log. The id comes from the same
	// helper a valid task uses, so a broken file keeps the identity it will have
	// once fixed.
	for path, message := range d.failures {
		id, idErr := task.IDFor(root, path)
		if idErr != nil {
			id = path
		}
		statuses = append(statuses, runtime.TaskStatus{
			ID:       id,
			State:    runtime.StateInvalid,
			Error:    message,
			YAMLPath: path,
		})
	}

	sort.Slice(statuses, func(i, j int) bool { return statuses[i].ID < statuses[j].ID })

	return runtime.Snapshot{
		GeneratedAt: time.Now(),
		TasksRoot:   root,
		Tasks:       statuses,
	}, nil
}

// Stop actively stops a running task.
//
// It implements runtime.Controller. Cancelling the run context is the single
// stop path: the supervisor owns the provider's Stop call, so a stop requested
// here and a stop caused by shutdown behave identically. The provider decides
// how to end the run, which is why Force is a hint rather than a guarantee: the
// scheduler does not own the process, so it cannot promise a signal.
//
// When the task has no in-flight run, the lock record left by a previous
// supervisor is tried instead. That path is best effort and is reported as such:
// the scheduler holds no context to cancel, so it can only forward a stop to the
// provider and cannot confirm the run ended.
func (d *Daemon) Stop(request runtime.StopRequest) (runtime.StopResult, error) {
	d.mu.Lock()
	run, running := d.runs[request.TaskID]
	if !running {
		d.mu.Unlock()
		return d.stopRecordedRun(request)
	}
	pid := run.info.PID
	runID := run.info.RunID
	run.stopped = true
	d.mu.Unlock()

	run.cancel()

	d.logger.Warn("run stop requested",
		slog.String("task", request.TaskID),
		slog.String("run_id", runID),
		slog.Int("pid", pid),
		slog.Bool("forced", request.Force),
	)
	return runtime.StopResult{TaskID: request.TaskID, PID: pid, Forced: request.Force}, nil
}

// stopRecordedRun asks the provider to stop the run named by the task's lock
// record, for a run this scheduler is not supervising.
//
// This exists because a run outlives the scheduler that started it: after a
// restart the run table is empty while the run may still be working, so without
// this path such a run could only be ended by the provider itself.
//
// It is best effort by construction. The scheduler has no context to cancel and
// no supervision loop to observe the outcome, so it forwards a stop and reports
// that it did. It cannot promise the run ended, and the caller must not read the
// result as confirmation.
//
// The lock is used as the safety check: the fallback only runs when the lock is
// free, which proves no live supervisor owns the task. Taking the lock also
// keeps a new round from starting while the stop is being forwarded.
func (d *Daemon) stopRecordedRun(request runtime.StopRequest) (runtime.StopResult, error) {
	item, err := d.taskByID(request.TaskID)
	if err != nil {
		return runtime.StopResult{}, err
	}

	held, acquired, err := lock.TryAcquire(item.LockPath)
	if err != nil {
		return runtime.StopResult{}, err
	}
	if !acquired {
		// A live supervisor owns the task, so the run table was merely stale.
		// Its own stop path is authoritative, and this request must not race it.
		return runtime.StopResult{}, fmt.Errorf("%w: %s", runtime.ErrTaskNotRunning, request.TaskID)
	}
	defer func() {
		if releaseErr := held.Release(); releaseErr != nil {
			d.logger.Warn("release lock after a recorded stop failed",
				slog.String("task", request.TaskID),
				slog.String("error", releaseErr.Error()),
			)
		}
	}()

	record, err := lock.ReadRecord(held.Path())
	if err != nil {
		return runtime.StopResult{}, err
	}
	if record.IsZero() {
		return runtime.StopResult{}, fmt.Errorf("%w: %s", runtime.ErrTaskNotRunning, request.TaskID)
	}

	implementation, err := d.providers.Provider(record.Provider)
	if err != nil {
		return runtime.StopResult{}, fmt.Errorf("resolve provider %q for the recorded run: %w", record.Provider, err)
	}

	handle := provider.Handle{
		Provider:  record.Provider,
		ID:        record.RunID,
		PID:       record.PID,
		StartedAt: record.StartedAt,
	}

	// The record may name a run that already ended, for example when the
	// provider finished after the supervisor died. Asking the provider first
	// keeps a stop from being sent to a run that is already over.
	observation, pollErr := implementation.Poll(context.Background(), handle)
	if pollErr != nil {
		d.logger.Warn("poll the recorded run failed, forwarding the stop anyway",
			slog.String("task", request.TaskID),
			slog.String("run_id", record.RunID),
			slog.String("error", pollErr.Error()),
		)
	} else if observation.State == provider.StateFinished {
		d.logger.Info("the recorded run already finished, nothing to stop",
			slog.String("task", request.TaskID),
			slog.String("run_id", record.RunID),
		)
		return runtime.StopResult{}, fmt.Errorf("%w: %s", runtime.ErrTaskNotRunning, request.TaskID)
	}

	if stopErr := implementation.Stop(context.Background(), handle); stopErr != nil {
		return runtime.StopResult{}, fmt.Errorf("stop the recorded run %q: %w", record.RunID, stopErr)
	}

	d.logger.Warn("stop forwarded to the provider for a run from a previous supervisor",
		slog.String("task", request.TaskID),
		slog.String("run_id", record.RunID),
		slog.String("provider", record.Provider),
		slog.Int("pid", record.PID),
		slog.Bool("forced", request.Force),
		slog.Bool("best_effort", true),
	)
	return runtime.StopResult{
		TaskID:     request.TaskID,
		PID:        record.PID,
		Forced:     request.Force,
		BestEffort: true,
	}, nil
}

// taskByID returns the loaded task with the given id.
func (d *Daemon) taskByID(id string) (task.Task, error) {
	trimmed := strings.TrimSpace(id)
	if trimmed == "" {
		return task.Task{}, fmt.Errorf("%w: empty task id", runtime.ErrTaskNotFound)
	}

	d.mu.Lock()
	item, exists := d.tasks[trimmed]
	d.mu.Unlock()

	if !exists {
		return task.Task{}, fmt.Errorf("%w: %s", runtime.ErrTaskNotFound, trimmed)
	}
	return item, nil
}

// newTraceID builds a trace id for one run.
//
// It combines the task id with the start time so every entry of one run shares
// an id and two runs of the same task remain distinguishable.
func newTraceID(taskID string) string {
	safe := strings.NewReplacer("/", "-", " ", "-").Replace(taskID)
	return fmt.Sprintf("%s-%d-%d", safe, time.Now().UnixNano(), os.Getpid())
}
