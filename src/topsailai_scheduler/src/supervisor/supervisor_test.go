package supervisor

import (
	"context"
	"encoding/json"
	"errors"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"topsailai_scheduler/lock"
	"topsailai_scheduler/provider"
)

// fakeProvider is a provider whose behaviour each test scripts.
type fakeProvider struct {
	mu sync.Mutex
	// states is the sequence of states returned by Poll. The last entry repeats
	// once the sequence is exhausted.
	states []provider.State
	// polls counts Poll calls.
	polls int
	// startErr is returned by Start when set.
	startErr error
	// pollErr is returned by Poll when set.
	pollErr error
	// stopCalls counts Stop calls.
	stopCalls int
	// started is closed once Start returns.
	started chan struct{}
}

func newFakeProvider(states ...provider.State) *fakeProvider {
	return &fakeProvider{states: states, started: make(chan struct{})}
}

func (f *fakeProvider) Name() string { return "fake" }

func (f *fakeProvider) Start(_ context.Context, _ provider.Request) (provider.Handle, error) {
	if f.startErr != nil {
		return provider.Handle{}, f.startErr
	}
	close(f.started)
	return provider.Handle{Provider: "fake", ID: "run-1", PID: 4242}, nil
}

func (f *fakeProvider) Poll(_ context.Context, _ provider.Handle) (provider.Observation, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	// Count the attempt before the error check: a failed poll is still an
	// attempt, and a test asserting repeated attempts must see it.
	index := f.polls
	f.polls++
	if f.pollErr != nil {
		return provider.Observation{}, f.pollErr
	}
	if index >= len(f.states) {
		index = len(f.states) - 1
	}
	return provider.Observation{State: f.states[index], ExitCode: 0}, nil
}

func (f *fakeProvider) Stop(_ context.Context, _ provider.Handle) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.stopCalls++
	return nil
}

func (f *fakeProvider) pollCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.polls
}

func (f *fakeProvider) stopCount() int {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.stopCalls
}

// TestLockIsHeldUntilTheRunFinishes is the core guarantee of the confirmed
// design: the lock must outlive the provider's start call.
//
// A provider returns a handle promptly and works in the background, so a lock
// released when Start returned would be free while the run was still working.
// The next tick would then start a second copy of the same task. This test
// starts a second round while the first is still running and requires it to be
// skipped.
func TestLockIsHeldUntilTheRunFinishes(t *testing.T) {
	lockPath := filepath.Join(t.TempDir(), "work.lock")

	// The first round stays running until the test releases it.
	release := make(chan struct{})
	first := newBlockingProvider(release)

	firstDone := make(chan Outcome, 1)
	go func() {
		firstDone <- Run(context.Background(), Options{
			Provider:     first,
			Request:      provider.Request{TaskID: "data/work"},
			LockPath:     lockPath,
			PollInterval: 5 * time.Millisecond,
		})
	}()
	// Wait until the first round is genuinely supervising, not merely started.
	<-first.started

	// A second round must be refused while the first is still running.
	second := newFakeProvider(provider.StateFinished)
	secondOutcome := Run(context.Background(), Options{
		Provider:     second,
		Request:      provider.Request{TaskID: "data/work"},
		LockPath:     lockPath,
		PollInterval: 5 * time.Millisecond,
	})
	if !secondOutcome.Skipped {
		t.Fatalf("second round was not skipped while the first was running: %+v", secondOutcome)
	}
	if second.pollCount() != 0 {
		t.Errorf("skipped round polled %d times, want 0", second.pollCount())
	}

	// Let the first round finish, then confirm the lock is free again.
	close(release)
	firstOutcome := <-firstDone
	if firstOutcome.Skipped {
		t.Fatal("first round was skipped, want it to run")
	}
	if firstOutcome.State != provider.StateFinished {
		t.Errorf("first round state = %q, want %q", firstOutcome.State, provider.StateFinished)
	}

	third := newFakeProvider(provider.StateFinished)
	thirdOutcome := Run(context.Background(), Options{
		Provider:     third,
		Request:      provider.Request{TaskID: "data/work"},
		LockPath:     lockPath,
		PollInterval: 5 * time.Millisecond,
	})
	if thirdOutcome.Skipped {
		t.Fatal("lock was still held after the run finished, want it released")
	}
}

// blockingProvider stays running until its release channel is closed.
type blockingProvider struct {
	release chan struct{}
	started chan struct{}
	once    sync.Once
}

// newBlockingProvider builds a provider whose started channel exists before the
// round begins. The channel must be created eagerly: a test that waits on a nil
// channel blocks forever, which is a hang rather than a failure.
func newBlockingProvider(release chan struct{}) *blockingProvider {
	return &blockingProvider{release: release, started: make(chan struct{})}
}

func (b *blockingProvider) Name() string { return "blocking" }

func (b *blockingProvider) Start(_ context.Context, _ provider.Request) (provider.Handle, error) {
	b.once.Do(func() { close(b.started) })
	return provider.Handle{Provider: "blocking", ID: "run-blocking"}, nil
}

func (b *blockingProvider) Poll(_ context.Context, _ provider.Handle) (provider.Observation, error) {
	select {
	case <-b.release:
		return provider.Observation{State: provider.StateFinished}, nil
	default:
		return provider.Observation{State: provider.StateRunning}, nil
	}
}

func (b *blockingProvider) Stop(_ context.Context, _ provider.Handle) error { return nil }

// TestPollUntilFinished proves supervision continues while the run reports
// running and ends when it reports finished.
func TestPollUntilFinished(t *testing.T) {
	fake := newFakeProvider(provider.StateRunning, provider.StateRunning, provider.StateFinished)
	outcome := Run(context.Background(), Options{
		Provider:     fake,
		Request:      provider.Request{TaskID: "data/work"},
		LockPath:     filepath.Join(t.TempDir(), "work.lock"),
		PollInterval: time.Millisecond,
	})
	if outcome.Err != nil {
		t.Fatalf("supervise: %v", outcome.Err)
	}
	if outcome.State != provider.StateFinished {
		t.Errorf("state = %q, want %q", outcome.State, provider.StateFinished)
	}
	if outcome.Polls != 3 {
		t.Errorf("polls = %d, want 3", outcome.Polls)
	}
	if outcome.Handle.ID != "run-1" {
		t.Errorf("handle id = %q, want %q", outcome.Handle.ID, "run-1")
	}
}

// TestUnknownStateKeepsSupervising proves an honest "unknown" answer does not
// end supervision. Ending on unknown would abandon a run that may still work.
func TestUnknownStateKeepsSupervising(t *testing.T) {
	fake := newFakeProvider(provider.StateUnknown, provider.StateUnknown, provider.StateFinished)
	outcome := Run(context.Background(), Options{
		Provider:     fake,
		Request:      provider.Request{TaskID: "data/work"},
		LockPath:     filepath.Join(t.TempDir(), "work.lock"),
		PollInterval: time.Millisecond,
	})
	if outcome.State != provider.StateFinished {
		t.Errorf("state = %q, want %q", outcome.State, provider.StateFinished)
	}
	if outcome.Polls != 3 {
		t.Errorf("polls = %d, want 3", outcome.Polls)
	}
}

// TestPollFailureDoesNotEndSupervision proves a failed poll is not read as
// "finished". A transient provider error must not abandon a live run.
func TestPollFailureDoesNotEndSupervision(t *testing.T) {
	fake := newFakeProvider(provider.StateFinished)
	fake.pollErr = errors.New("provider temporarily unavailable")

	ctx, cancel := context.WithTimeout(context.Background(), 60*time.Millisecond)
	defer cancel()

	outcome := Run(ctx, Options{
		Provider:     fake,
		Request:      provider.Request{TaskID: "data/work"},
		LockPath:     filepath.Join(t.TempDir(), "work.lock"),
		PollInterval: time.Millisecond,
	})
	if outcome.State == provider.StateFinished {
		t.Error("a failed poll was read as finished, want supervision to continue")
	}
	// The round ends because its deadline elapsed, so the outcome is a timeout,
	// not a cancellation. Either way supervision continued past the failures.
	if !outcome.TimedOut {
		t.Errorf("timed out = %v, want true", outcome.TimedOut)
	}
	if fake.pollCount() < 2 {
		t.Errorf("polls = %d, want repeated attempts", fake.pollCount())
	}
	if fake.stopCount() != 1 {
		t.Errorf("stop calls = %d, want 1", fake.stopCount())
	}
}

// TestTimeoutStopsTheRun proves the round timeout ends supervision and asks the
// provider to stop the run.
func TestTimeoutStopsTheRun(t *testing.T) {
	fake := newFakeProvider(provider.StateRunning)
	outcome := Run(context.Background(), Options{
		Provider:     fake,
		Request:      provider.Request{TaskID: "data/work"},
		LockPath:     filepath.Join(t.TempDir(), "work.lock"),
		PollInterval: time.Millisecond,
		Timeout:      40 * time.Millisecond,
	})
	if !outcome.TimedOut {
		t.Errorf("timed out = %v, want true", outcome.TimedOut)
	}
	if outcome.Canceled {
		t.Errorf("canceled = %v, want false", outcome.Canceled)
	}
	if fake.stopCount() != 1 {
		t.Errorf("stop calls = %d, want 1", fake.stopCount())
	}
}

// TestCancelStopsTheRun proves a cancelled context ends supervision and asks the
// provider to stop the run.
func TestCancelStopsTheRun(t *testing.T) {
	fake := newFakeProvider(provider.StateRunning)
	ctx, cancel := context.WithCancel(context.Background())
	go func() {
		<-fake.started
		cancel()
	}()

	outcome := Run(ctx, Options{
		Provider:     fake,
		Request:      provider.Request{TaskID: "data/work"},
		LockPath:     filepath.Join(t.TempDir(), "work.lock"),
		PollInterval: time.Millisecond,
	})
	if !outcome.Canceled {
		t.Errorf("canceled = %v, want true", outcome.Canceled)
	}
	if outcome.TimedOut {
		t.Errorf("timed out = %v, want false", outcome.TimedOut)
	}
	if fake.stopCount() != 1 {
		t.Errorf("stop calls = %d, want 1", fake.stopCount())
	}
}

// TestStartFailureReleasesTheLock proves a failed start does not leave the task
// locked, which would block every later round.
func TestStartFailureReleasesTheLock(t *testing.T) {
	lockPath := filepath.Join(t.TempDir(), "work.lock")
	failing := newFakeProvider(provider.StateFinished)
	failing.startErr = errors.New("provider refused to start")

	outcome := Run(context.Background(), Options{
		Provider:     failing,
		Request:      provider.Request{TaskID: "data/work"},
		LockPath:     lockPath,
		PollInterval: time.Millisecond,
	})
	if outcome.Err == nil {
		t.Fatal("start failure was not reported")
	}

	held, acquired, err := lock.TryAcquire(lockPath)
	if err != nil {
		t.Fatalf("acquire lock: %v", err)
	}
	if !acquired {
		t.Fatal("lock was left held after a failed start")
	}
	if releaseErr := held.Release(); releaseErr != nil {
		t.Fatalf("release lock: %v", releaseErr)
	}
}

// TestMissingConfigurationIsReported proves a round without a provider or lock
// path fails loudly instead of silently doing nothing.
func TestMissingConfigurationIsReported(t *testing.T) {
	noProvider := Run(context.Background(), Options{LockPath: "/tmp/x.lock"})
	if noProvider.Err == nil {
		t.Error("a round without a provider was accepted")
	}

	noLock := Run(context.Background(), Options{Provider: newFakeProvider(provider.StateFinished)})
	if noLock.Err == nil {
		t.Error("a round without a lock path was accepted")
	}
}

// TestCallbacksReportProgress proves the start and observation callbacks fire so
// the daemon can record the run identity and its latest state.
func TestCallbacksReportProgress(t *testing.T) {
	fake := newFakeProvider(provider.StateRunning, provider.StateFinished)

	var startedHandle provider.Handle
	var observations []provider.Observation

	outcome := Run(context.Background(), Options{
		Provider:     fake,
		Request:      provider.Request{TaskID: "data/work"},
		LockPath:     filepath.Join(t.TempDir(), "work.lock"),
		PollInterval: time.Millisecond,
		OnStart:      func(handle provider.Handle) { startedHandle = handle },
		OnObservation: func(observation provider.Observation) {
			observations = append(observations, observation)
		},
	})
	if outcome.Err != nil {
		t.Fatalf("supervise: %v", outcome.Err)
	}
	if startedHandle.ID != "run-1" {
		t.Errorf("started handle id = %q, want %q", startedHandle.ID, "run-1")
	}
	if len(observations) != 2 {
		t.Fatalf("observations = %d, want 2", len(observations))
	}
	if observations[0].State != provider.StateRunning {
		t.Errorf("first observation = %q, want %q", observations[0].State, provider.StateRunning)
	}
	if observations[1].State != provider.StateFinished {
		t.Errorf("second observation = %q, want %q", observations[1].State, provider.StateFinished)
	}
}

// TestOutcomeCarriesTiming proves the outcome records when supervision began and
// ended, so a run's duration is observable.
func TestOutcomeCarriesTiming(t *testing.T) {
	outcome := Run(context.Background(), Options{
		Provider:     newFakeProvider(provider.StateFinished),
		Request:      provider.Request{TaskID: "data/work"},
		LockPath:     filepath.Join(t.TempDir(), "work.lock"),
		PollInterval: time.Millisecond,
	})
	if outcome.StartedAt.IsZero() {
		t.Error("started at is zero")
	}
	if outcome.FinishedAt.IsZero() {
		t.Error("finished at is zero")
	}
	if outcome.FinishedAt.Before(outcome.StartedAt) {
		t.Error("finished at is before started at")
	}
}

// writeRecordFile seeds a lock file with a record, standing in for a supervisor
// that died while a run was in flight.
func writeRecordFile(t *testing.T, path string, record lock.Record) {
	t.Helper()
	document, err := json.Marshal(record)
	if err != nil {
		t.Fatalf("encode record: %v", err)
	}
	if writeErr := os.WriteFile(path, document, 0o600); writeErr != nil {
		t.Fatalf("write record: %v", writeErr)
	}
}

// TestStaleRecordForAFinishedRunIsCleared verifies that a record naming a run
// that already ended does not block the task forever.
//
// This is the common case after a restart: the scheduler died, the run finished
// on its own, and the record is simply out of date.
func TestStaleRecordForAFinishedRunIsCleared(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")
	writeRecordFile(t, path, lock.Record{
		RunID:    "run-old",
		Provider: "fake",
		PID:      1111,
	})

	implementation := newFakeProvider(provider.StateFinished, provider.StateFinished)
	outcome := Run(context.Background(), Options{
		Provider:     implementation,
		Request:      provider.Request{TaskID: "demo"},
		LockPath:     path,
		PollInterval: time.Millisecond,
	})

	if outcome.Err != nil {
		t.Fatalf("unexpected error: %v", outcome.Err)
	}
	if !outcome.Reconciled {
		t.Error("expected the stale record to be reconciled")
	}
	if outcome.Skipped {
		t.Error("a finished run must not block the round")
	}
	if outcome.Handle.ID != "run-1" {
		t.Errorf("expected a new run to start, got %q", outcome.Handle.ID)
	}

	record, err := lock.ReadRecord(path)
	if err != nil {
		t.Fatalf("read record: %v", err)
	}
	if !record.IsZero() {
		t.Errorf("expected the record to be cleared after the run finished, got %+v", record)
	}
}

// TestRecordForARunningRunSkipsTheRound verifies the guarantee this mechanism
// exists for: a run left in flight by a dead scheduler must not be duplicated.
func TestRecordForARunningRunSkipsTheRound(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")
	writeRecordFile(t, path, lock.Record{
		RunID:    "run-old",
		Provider: "fake",
		PID:      1111,
	})

	implementation := newFakeProvider(provider.StateRunning)
	outcome := Run(context.Background(), Options{
		Provider:     implementation,
		Request:      provider.Request{TaskID: "demo"},
		LockPath:     path,
		PollInterval: time.Millisecond,
	})

	if outcome.Err != nil {
		t.Fatalf("unexpected error: %v", outcome.Err)
	}
	if !outcome.Skipped {
		t.Fatal("expected the round to be skipped while the recorded run is alive")
	}
	if outcome.ReconciledState != provider.StateRunning {
		t.Errorf("expected the reconciled state to be reported, got %q", outcome.ReconciledState)
	}
	if implementation.pollCount() != 1 {
		t.Errorf("expected exactly one reconcile poll, got %d", implementation.pollCount())
	}

	// The record must survive, so the next tick can check again.
	record, err := lock.ReadRecord(path)
	if err != nil {
		t.Fatalf("read record: %v", err)
	}
	if record.RunID != "run-old" {
		t.Errorf("expected the record to be kept, got %+v", record)
	}
}

// TestRecordWithAnUnknownStateSkipsTheRound verifies that an unanswerable
// provider is treated as busy.
//
// A provider that cannot say whether the run ended is not evidence that it did,
// so starting a second copy would risk duplicated work.
func TestRecordWithAnUnknownStateSkipsTheRound(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")
	writeRecordFile(t, path, lock.Record{RunID: "run-old", Provider: "fake"})

	implementation := newFakeProvider(provider.StateUnknown)
	outcome := Run(context.Background(), Options{
		Provider:     implementation,
		Request:      provider.Request{TaskID: "demo"},
		LockPath:     path,
		PollInterval: time.Millisecond,
	})

	if outcome.Err != nil {
		t.Fatalf("unexpected error: %v", outcome.Err)
	}
	if !outcome.Skipped {
		t.Fatal("expected an unknown state to be treated as still busy")
	}
}

// TestReconcilePollFailureSkipsTheRound verifies that a provider error during
// reconciliation is treated as busy rather than as a finished run.
func TestReconcilePollFailureSkipsTheRound(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")
	writeRecordFile(t, path, lock.Record{RunID: "run-old", Provider: "fake"})

	implementation := newFakeProvider(provider.StateFinished)
	implementation.pollErr = errors.New("provider unreachable")

	outcome := Run(context.Background(), Options{
		Provider:     implementation,
		Request:      provider.Request{TaskID: "demo"},
		LockPath:     path,
		PollInterval: time.Millisecond,
	})

	if outcome.Err != nil {
		t.Fatalf("unexpected error: %v", outcome.Err)
	}
	if !outcome.Skipped {
		t.Fatal("expected a failed reconcile poll to skip the round")
	}
}

// TestRecordFromAnotherProviderIsReported verifies that a record naming a
// different provider is refused instead of being checked against the wrong one.
func TestRecordFromAnotherProviderIsReported(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")
	writeRecordFile(t, path, lock.Record{RunID: "run-old", Provider: "other"})

	implementation := newFakeProvider(provider.StateFinished)
	outcome := Run(context.Background(), Options{
		Provider:     implementation,
		Request:      provider.Request{TaskID: "demo"},
		LockPath:     path,
		PollInterval: time.Millisecond,
	})

	if outcome.Err == nil {
		t.Fatal("expected a provider mismatch to be reported")
	}
	if outcome.Skipped {
		t.Error("a mismatch is an error, not a skip")
	}
}

// TestNoRecordStartsNormally verifies that a task with no history is unaffected.
func TestNoRecordStartsNormally(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")

	implementation := newFakeProvider(provider.StateFinished)
	outcome := Run(context.Background(), Options{
		Provider:     implementation,
		Request:      provider.Request{TaskID: "demo"},
		LockPath:     path,
		PollInterval: time.Millisecond,
	})

	if outcome.Err != nil {
		t.Fatalf("unexpected error: %v", outcome.Err)
	}
	if outcome.Reconciled {
		t.Error("expected no reconciliation when there is no record")
	}
	if outcome.Skipped {
		t.Error("expected the round to start")
	}
	if outcome.Handle.ID != "run-1" {
		t.Errorf("expected the run to start, got %q", outcome.Handle.ID)
	}
}

// TestRecordIsWrittenWhileSupervising verifies that a supervisor leaves the
// breadcrumb a restart needs, and that it names the run it started.
func TestRecordIsWrittenWhileSupervising(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")

	implementation := newBlockingProvider(make(chan struct{}))
	done := make(chan Outcome, 1)
	go func() {
		done <- Run(context.Background(), Options{
			Provider:     implementation,
			Request:      provider.Request{TaskID: "demo"},
			LockPath:     path,
			PollInterval: time.Millisecond,
		})
	}()

	// Wait for the run to be recorded, which is what a restart would read.
	deadline := time.Now().Add(2 * time.Second)
	var record lock.Record
	for time.Now().Before(deadline) {
		read, err := lock.ReadRecord(path)
		if err != nil {
			t.Fatalf("read record: %v", err)
		}
		if !read.IsZero() {
			record = read
			break
		}
		time.Sleep(5 * time.Millisecond)
	}
	if record.IsZero() {
		t.Fatal("expected a record to be written while supervising")
	}
	if record.Provider != "blocking" {
		t.Errorf("expected the provider name, got %q", record.Provider)
	}
	if record.SchedulerPID != os.Getpid() {
		t.Errorf("expected scheduler pid %d, got %d", os.Getpid(), record.SchedulerPID)
	}

	implementation.release <- struct{}{}
	<-done
}

// TestTimeoutKeepsTheRecord verifies that a run which was only asked to stop
// keeps its record, because the next start must still check whether it obeyed.
func TestTimeoutKeepsTheRecord(t *testing.T) {
	path := filepath.Join(t.TempDir(), "task.lock")

	implementation := newFakeProvider(provider.StateRunning)
	outcome := Run(context.Background(), Options{
		Provider:     implementation,
		Request:      provider.Request{TaskID: "demo"},
		LockPath:     path,
		PollInterval: time.Millisecond,
		Timeout:      20 * time.Millisecond,
	})

	if !outcome.TimedOut {
		t.Fatalf("expected a timeout, got %+v", outcome)
	}

	record, err := lock.ReadRecord(path)
	if err != nil {
		t.Fatalf("read record: %v", err)
	}
	if record.IsZero() {
		t.Fatal("expected the record to survive a timeout, so the next start can check the run")
	}
}
