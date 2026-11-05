package tui

import (
	"context"
	"io"
	"os"
	"strings"
	"testing"
)

// noPromptStream fails immediately if the callback path ever starts pre-reading.
type noPromptStream struct{ t *testing.T }

// Read forbids reading before an explicit prompt callback.
func (r noPromptStream) Read([]byte) (int, error) {
	r.t.Error("callback path read stream")
	return 0, io.EOF
}

// TestPromptReaderGating checks prompt completion, answer isolation and stream independence.
func TestPromptReaderGating(t *testing.T) {
	var out, diagnostics strings.Builder
	steps := 0
	read := func(ctx context.Context, prompt string, history bool, limit int) (string, bool, error) {
		if ctx.Err() != nil || limit != 8192 {
			t.Fatalf("ctx=%v limit=%d", ctx.Err(), limit)
		}
		steps++
		switch steps {
		case 1:
			if !history || !strings.HasSuffix(out.String(), "workspace> ") || prompt != "workspace> " {
				t.Fatalf("prompt=%q history=%v out=%q", prompt, history, out.String())
			}
			return "start", false, nil
		case 2:
			if history || !strings.HasSuffix(out.String(), "start.endpoint> ") {
				t.Fatalf("history=%v out=%q", history, out.String())
			}
			return "cancel", false, nil
		default:
			return "quit", false, nil
		}
	}
	if err := RunInteractive(context.Background(), inputStub(), noPromptStream{t}, &out, &diagnostics, InteractiveOptions{ReadLine: read}); err != nil {
		t.Fatal(err)
	}
	if steps != 3 || !strings.Contains(out.String(), "start cancelled") || diagnostics.Len() != 0 {
		t.Fatalf("steps=%d out=%q err=%q", steps, out.String(), diagnostics.String())
	}
}

// TestNextPromptLineCancellation preserves cancellation without a live input channel.
func TestNextPromptLineCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	got, ok := nextPromptLine(ctx, nil)
	if !ok || got.err != context.Canceled {
		t.Fatalf("%+v %v", got, ok)
	}
	done := make(chan struct{})
	c := promptContext(done)
	if c.Err() != nil || c.Value("x") != nil {
		t.Fatal("invalid initial context")
	}
	if _, ok := c.Deadline(); ok {
		t.Fatal("unexpected deadline")
	}
	close(done)
	if c.Err() != context.Canceled {
		t.Fatal(c.Err())
	}
}

// TestPromptReaderChildFailures rejects fatal wizard input and recovers from Ctrl-C.
func TestPromptReaderChildFailures(t *testing.T) {
	for _, failure := range []error{ErrInteractiveInterrupt, io.ErrUnexpectedEOF, io.EOF} {
		var out, diagnostics strings.Builder
		calls := 0
		read := func(ctx context.Context, prompt string, history bool, limit int) (string, bool, error) {
			calls++
			switch calls {
			case 1:
				return "start", false, nil
			case 2:
				if prompt != "start.endpoint> " || history {
					t.Fatalf("prompt=%q history=%v", prompt, history)
				}
				return "", false, failure
			default:
				return "quit", false, nil
			}
		}
		stub := inputStub()
		err := RunInteractive(context.Background(), stub, noPromptStream{t}, &out, &diagnostics, InteractiveOptions{ReadLine: read})
		if failure == io.ErrUnexpectedEOF && err != failure {
			t.Fatalf("err=%v", err)
		}
		if failure != io.ErrUnexpectedEOF && err != nil {
			t.Fatal(err)
		}
		if stub.admit != 0 {
			t.Fatal("input failure admitted command")
		}
		if failure == ErrInteractiveInterrupt && calls != 3 {
			t.Fatalf("calls=%d", calls)
		}
	}
}

// TestPromptReaderExternalSignal cancels child reads without exiting the recovered REPL.
func TestPromptReaderExternalSignal(t *testing.T) {
	var out, diagnostics strings.Builder
	signals := make(chan os.Signal, 1)
	calls := 0
	read := func(ctx context.Context, _ string, _ bool, _ int) (string, bool, error) {
		calls++
		if calls == 1 {
			return "start", false, nil
		}
		if calls == 2 {
			signals <- os.Interrupt
			<-ctx.Done()
			return "", false, ctx.Err()
		}
		return "quit", false, nil
	}
	if err := RunInteractive(context.Background(), inputStub(), noPromptStream{t}, &out, &diagnostics, InteractiveOptions{ReadLine: read, Interrupt: signals}); err != nil {
		t.Fatal(err)
	}
	if calls != 3 || !strings.Contains(diagnostics.String(), "interrupted") {
		t.Fatalf("calls=%d diagnostics=%q", calls, diagnostics.String())
	}
}
