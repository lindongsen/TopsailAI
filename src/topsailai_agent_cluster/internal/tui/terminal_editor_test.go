package tui

import (
	"context"
	"errors"
	"io"
	"os"
	"strings"
	"testing"
	"time"
)

// editorTestInput tracks deadlines while returning injected terminal bytes.
type editorTestInput struct {
	io.Reader
	deadlineErr error
	deadlines   int
}

// SetReadDeadline exposes deadline failures without modifying process state.
func (f *editorTestInput) SetReadDeadline(time.Time) error { f.deadlines++; return f.deadlineErr }

// TestTerminalEditorLines checks actual decoder-model composition and history reuse.
func TestTerminalEditorLines(t *testing.T) {
	input := &editorTestInput{Reader: strings.NewReader("helx\x7fp\r\x1b[A\rsecret\r\x1b[A\r")}
	var out strings.Builder
	restored := 0
	editor := NewTerminalEditor(input, &out, func() int { return 40 }, func() (func() error, error) { return func() error { restored++; return nil }, nil })
	for _, c := range []struct {
		history bool
		want    string
	}{{true, "help"}, {true, "help"}, {false, "secret"}, {true, "help"}} {
		got, bad, err := editor.ReadLine(context.Background(), "cluster> ", c.history, 32)
		if err != nil || bad || got != c.want {
			t.Fatalf("%q %v %v", got, bad, err)
		}
	}
	if restored != 4 || len(editor.editor.history) != 1 {
		t.Fatalf("restore=%d history=%v", restored, editor.editor.history)
	}
}

// TestTerminalEditorRejectAndRestore verifies no partial text escapes any failure.
func TestTerminalEditorRejectAndRestore(t *testing.T) {
	sentinel := errors.New("restore failed")
	for _, c := range []struct {
		input   string
		restore error
		want    error
		bad     bool
	}{
		{"abcde\r", nil, nil, true}, {"partial", nil, io.EOF, false}, {"\x03", nil, ErrInteractiveInterrupt, false},
		{"\x04", nil, io.EOF, false}, {"safe\x1b[200~evil\r", nil, errLineKey, false}, {"ok\r", sentinel, sentinel, false},
	} {
		var out strings.Builder
		calls := 0
		editor := NewTerminalEditor(&editorTestInput{Reader: strings.NewReader(c.input)}, &out, func() int { return 0 }, func() (func() error, error) { return func() error { calls++; return c.restore }, nil })
		got, bad, err := editor.ReadLine(context.Background(), "long prompt> ", true, 5)
		if got != "" || bad != c.bad || !errors.Is(err, c.want) || calls != 1 {
			t.Fatalf("input=%q got=%q bad=%v err=%v restores=%d", c.input, got, bad, err, calls)
		}
	}
}

// TestTerminalEditorFailures preserves enable, deadline and write failures.
func TestTerminalEditorFailures(t *testing.T) {
	sentinel := errors.New("injected failure")
	editor := NewTerminalEditor(nil, nil, nil, func() (func() error, error) { return nil, sentinel })
	if _, _, err := editor.ReadLine(context.Background(), "", true, 10); err != sentinel {
		t.Fatal(err)
	}
	ctx, cancel := context.WithCancel(context.Background())
	cancel()
	if _, _, err := editor.ReadLine(ctx, "", true, 10); err != context.Canceled {
		t.Fatal(err)
	}
	for _, writer := range []io.Writer{io.Discard, exampleFailureWriter{err: sentinel}} {
		restored := false
		editor = NewTerminalEditor(&editorTestInput{Reader: strings.NewReader("x"), deadlineErr: sentinel}, writer, func() int { return 80 }, func() (func() error, error) { return func() error { restored = true; return nil }, nil })
		if got, _, err := editor.ReadLine(context.Background(), "", true, 10); got != "" || !errors.Is(err, sentinel) || !restored {
			t.Fatalf("%q %v restored=%v", got, err, restored)
		}
	}
}

// deadlineOnlyInput simulates terminal polling until cancellation or Escape timeout.
type deadlineOnlyInput struct {
	prefix string
	cancel context.CancelFunc
}

// SetReadDeadline accepts deadlines on this isolated test input.
func (f *deadlineOnlyInput) SetReadDeadline(time.Time) error { return nil }

// Read emits prefix bytes, then simulates a completed deadline poll.
func (f *deadlineOnlyInput) Read(p []byte) (int, error) {
	if len(f.prefix) > 0 {
		p[0] = f.prefix[0]
		f.prefix = f.prefix[1:]
		return 1, nil
	}
	if f.cancel != nil {
		f.cancel()
	}
	return 0, os.ErrDeadlineExceeded
}

// TestTerminalByteReaderCancellation does not swallow parent cancellation as a timeout.
func TestTerminalByteReaderCancellation(t *testing.T) {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()
	input := &deadlineOnlyInput{cancel: cancel}
	reader := &terminalByteReader{ctx: ctx, input: input}
	if _, err := reader.Read(make([]byte, 1)); err != context.Canceled {
		t.Fatal(err)
	}
	if n, err := reader.Read(nil); n != 0 || err != nil {
		t.Fatalf("%d %v", n, err)
	}
	reader = &terminalByteReader{ctx: context.Background(), input: input, escapeDeadline: time.Now().Add(-time.Second)}
	if _, err := reader.Read(make([]byte, 1)); !errors.Is(err, errLineKey) {
		t.Fatal(err)
	}
}

// TestTerminalPromptRowOwnership prevents stranded prompts while preserving question rows.
func TestTerminalPromptRowOwnership(t *testing.T) {
	for _, prompt := range []string{"cluster> ", "cluster[host/session]> ", "start.folder> ", "start.task> ", "\nanswer> "} {
		for _, width := range []int{12, 80} {
			var out strings.Builder
			editor := NewTerminalEditor(&editorTestInput{Reader: strings.NewReader("\r")}, &out, func() int { return width }, func() (func() error, error) { return func() error { return nil }, nil })
			if _, _, err := editor.ReadLine(context.Background(), prompt, false, 32); err != nil {
				t.Fatal(err)
			}
			wantRows := 1
			if strings.HasPrefix(prompt, "\n") {
				wantRows = 2
			}
			if got := strings.Count(out.String(), "\r\n"); got != wantRows {
				t.Fatalf("prompt=%q width=%d rows=%d output=%q", prompt, width, got, out.String())
			}
			if !strings.HasPrefix(prompt, "\n") && !strings.HasPrefix(out.String(), "\r\x1b[2K") {
				t.Fatalf("named prompt moved rows: %q", out.String())
			}
		}
	}
}
