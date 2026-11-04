package tui

import (
	"bufio"
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"
)

const unitC17ChildEnv = "TOPSAILAI_C17_STDIN_CHILD"

// unitC17ChildMode is an entrypoint-only configuration, never a production switch.
type unitC17ChildMode struct {
	Owned bool
	Cause string
}

// unitC17ChildResult carries actual descriptor, callback and error observations.
type unitC17ChildResult struct {
	Mode                    unitC17ChildMode
	ExactCause              bool
	DescriptorOpen          bool
	ZeroDelta               bool
	ExactOutput             bool
	Entries, Returns, Exits int
}

// unitC17ChildMessage separates protocol evidence from Go test framework output.
type unitC17ChildMessage struct {
	Kind   string
	Result unitC17ChildResult
}

// unitC17Emit publishes one complete protocol record on the child stdout.
func unitC17Emit(message unitC17ChildMessage) error {
	data, err := json.Marshal(message)
	if err != nil {
		return err
	}
	_, err = fmt.Fprintln(os.Stdout, "C17_PROTOCOL "+string(data))
	return err
}

// TestUnitCBatch2StdinChild runs only when explicitly configured by its parent.
func TestUnitCBatch2StdinChild(t *testing.T) {
	raw := os.Getenv(unitC17ChildEnv)
	if raw == "" {
		t.Skip("child entry requires explicit parent configuration")
	}
	var mode unitC17ChildMode
	if err := json.Unmarshal([]byte(raw), &mode); err != nil {
		t.Fatal(err)
	}
	if mode.Cause != "parent" && mode.Cause != "deadline" && mode.Cause != "fatal" {
		t.Fatal("C17 invalid child mode")
	}
	parent, cancel := context.WithCancel(context.Background())
	defer cancel()
	deadline := newUnitCBatch2Deadline()
	var ctx context.Context = parent
	if mode.Cause == "deadline" {
		ctx = deadline
	}
	api := newUnitCAPI()
	out := &unitCStageWriter{changed: make(chan struct{}, 1)}
	diagnostics := &unitCStageWriter{changed: make(chan struct{}, 1)}
	gate := newUnitCWriteGate()
	ledger := newUnitCBatch2WatcherLedger()
	ledger.release()
	run := &unitCBatch2Run{done: make(chan struct{})}
	t.Cleanup(func() {
		cancel()
		deadline.Arm()
		gate.abort()
		ledger.release()
		waitClosed(t, run.done, "C17 child cleanup")
	})
	go func() {
		run.err = RunInteractive(ctx, api, os.Stdin, &unitC10Writer{stage: "output", base: out, gate: gate}, diagnostics,
			InteractiveOptions{CloseInput: mode.Owned, Interrupt: make(chan os.Signal), watcherBeforeDone: ledger.beforeDone, watcherExit: ledger.afterWait})
		close(run.done)
	}()
	ready := unitCBatch2ReadyText(startFieldEndpoint)
	awaitExactOutput(t, out, ready)
	baseline, intents := api.snapshot()
	want := error(context.Canceled)
	sentinel := errors.New("C17 child fatal writer")
	if mode.Cause == "fatal" {
		gate.arm(nil, false)
	}
	if err := unitC17Emit(unitC17ChildMessage{Kind: "READY"}); err != nil {
		t.Fatal(err)
	}
	switch mode.Cause {
	case "parent":
		cancel()
	case "deadline":
		deadline.Arm()
		want = context.DeadlineExceeded
	case "fatal":
		attempt := <-gate.hit
		help, stage := c10ExpectedWrite("help")
		if attempt.Text != help || attempt.Stage != stage {
			t.Fatal("C17 child actual help boundary mismatch")
		}
		gate.reply(attempt, sentinel)
		want = sentinel
	}
	waitClosed(t, run.done, "C17 child runner return without parent EOF")
	_, statErr := os.Stdin.Stat()
	after, afterIntents := api.snapshot()
	facts := ledger.snapshot()
	result := unitC17ChildResult{Mode: mode, ExactCause: run.err == want && errors.Is(run.err, want),
		DescriptorOpen: statErr == nil, ZeroDelta: unitCAPIAdd(baseline, after) == (unitCAPICounts{}) && len(afterIntents) == len(intents),
		ExactOutput: out.String() == ready && diagnostics.String() == "", Entries: facts.entries, Returns: facts.returns, Exits: facts.exits}
	if mode.Owned && !errors.Is(statErr, os.ErrClosed) {
		t.Fatalf("C17 child result: Stat=%v want closed", statErr)
	}
	ledger.assertReleasedOrder(t)
	// B2_CHILD_RESULT: detached child result sensitivity seam.
	if err := unitC17Emit(unitC17ChildMessage{Kind: "RESULT", Result: result}); err != nil {
		t.Fatal(err)
	}
	// B2_CHILD_WAIT: actual child process exit action seam.
}

// TestUnitCBatch2StdinOwnership owns six real children and their pipe descriptors.
func TestUnitCBatch2StdinOwnership(t *testing.T) {
	for _, owned := range []bool{false, true} {
		for _, cause := range []string{"parent", "deadline", "fatal"} {
			t.Run(fmt.Sprintf("close-%t/%s", owned, cause), func(t *testing.T) {
				runUnitC17Stdin(t, unitC17ChildMode{Owned: owned, Cause: cause})
			})
		}
	}
}

// runUnitC17Stdin retains its pipe writer through RESULT, then reaps exactly once.
func runUnitC17Stdin(t *testing.T, mode unitC17ChildMode) {
	t.Helper()
	executable, err := os.Executable()
	if err != nil {
		t.Fatal(err)
	}
	input, writer, err := os.Pipe()
	if err != nil {
		t.Fatal(err)
	}
	defer input.Close()
	defer writer.Close()
	cmd := exec.Command(executable, "-test.run=^TestUnitCBatch2StdinChild$", "-test.count=1", "-test.v")
	for _, setting := range os.Environ() {
		if !strings.HasPrefix(setting, unitC17ChildEnv+"=") {
			cmd.Env = append(cmd.Env, setting)
		}
	}
	data, err := json.Marshal(mode)
	if err != nil {
		t.Fatal(err)
	}
	cmd.Env = append(cmd.Env, unitC17ChildEnv+"="+string(data))
	cmd.Stdin = input
	stdout, err := cmd.StdoutPipe()
	if err != nil {
		t.Fatal(err)
	}
	var stderr bytes.Buffer
	cmd.Stderr = &stderr
	started := time.Now()
	if err := cmd.Start(); err != nil {
		t.Fatal(err)
	}
	_ = input.Close()
	messages := make(chan unitC17ChildMessage, 8)
	drainDone := make(chan struct{})
	var scanErr error
	go func() {
		defer close(drainDone)
		defer close(messages)
		scanner := bufio.NewScanner(stdout)
		for scanner.Scan() {
			line := scanner.Text()
			if !strings.HasPrefix(line, "C17_PROTOCOL ") {
				continue
			}
			var message unitC17ChildMessage
			if err := json.Unmarshal([]byte(strings.TrimPrefix(line, "C17_PROTOCOL ")), &message); err != nil {
				scanErr = err
				continue
			}
			messages <- message
		}
		if err := scanner.Err(); err != nil {
			scanErr = err
		}
	}()
	waited := false
	t.Cleanup(func() {
		_ = writer.Close()
		if !waited {
			t.Logf("C17 cleanup exact owned child pid=%d", cmd.Process.Pid)
			_ = cmd.Process.Kill()
			_ = cmd.Wait()
			waited = true
		}
		waitClosed(t, drainDone, "C17 stdout drainer join")
	})
	if _, err := io.WriteString(writer, "start\n"); err != nil {
		t.Fatal(err)
	}
	ready := unitC17Receive(t, messages)
	if ready.Kind != "READY" {
		t.Fatalf("C17 child result: first=%+v", ready)
	}
	if mode.Cause == "fatal" {
		if _, err := io.WriteString(writer, "help\n"); err != nil {
			t.Fatal(err)
		}
	}
	message := unitC17Receive(t, messages)
	// The parent's writer is still open here: no EOF has been supplied to the child.
	if message.Kind != "RESULT" {
		t.Fatalf("C17 child result: missing RESULT: %+v", message)
	}
	result := message.Result
	if result.Mode != mode || !result.ExactCause || result.DescriptorOpen == mode.Owned || !result.ZeroDelta || !result.ExactOutput || result.Entries != 1 || result.Returns != 1 || result.Exits != 1 {
		t.Fatalf("C17 child result: %+v expected=%+v", result, mode)
	}
	_ = writer.Close()
	waitClosed(t, drainDone, "C17 stdout completion")
	waitErr := cmd.Wait()
	waited = true
	if waitErr != nil || scanErr != nil {
		t.Fatalf("C17 child wait: wait=%v scan=%v stderr=%q", waitErr, scanErr, stderr.String())
	}
	t.Logf("C17 actual stdin pid=%d mode=%+v RESULT=%+v Wait=0 elapsed=%s writer-retained-through-RESULT=true", cmd.Process.Pid, mode, result, time.Since(started))
}

// unitC17Receive uses a watchdog only to report a failed child protocol.
func unitC17Receive(t *testing.T, messages <-chan unitC17ChildMessage) unitC17ChildMessage {
	t.Helper()
	select {
	case message, ok := <-messages:
		if !ok {
			t.Fatal("C17 child result: stdout ended before protocol completion")
		}
		return message
	case <-time.After(10 * time.Second):
		t.Fatal("C17 child result: protocol watchdog expired")
		return unitC17ChildMessage{}
	}
}
