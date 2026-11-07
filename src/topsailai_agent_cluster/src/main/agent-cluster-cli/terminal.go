package main

import (
	"fmt"
	"io"
	"os"
	"strings"
	"time"
	"topsailai_agent_cluster/internal/tui"

	"golang.org/x/term"
)

// terminalOutput exposes the actual output terminal size, including after resize.
// full disables table truncation, so a narrow terminal wraps instead of clipping.
// color is the colour policy resolved from this output stream, so a renderer
// reached through this boundary honours --no-color and a redirected stream
// without probing global terminal state.
type terminalOutput struct {
	io.Writer
	full  bool
	color tui.ColorPolicy
}

// ColorPolicy reports the colour policy of this output boundary.
func (out terminalOutput) ColorPolicy() tui.ColorPolicy { return out.color }

// TerminalWidth leaves files and pipes unchanged when no terminal size is known.
func (out terminalOutput) TerminalWidth() int {
	file, ok := out.Writer.(interface{ Fd() uintptr })
	if !ok {
		return 0
	}
	width, _, err := term.GetSize(int(file.Fd()))
	if err != nil {
		return 0
	}
	return width
}

// TableLayout reports the width and truncation policy of this output boundary.
// The width stays the real terminal width even when truncation is disabled, so
// the interactive line editor keeps its prompt budget.
func (out terminalOutput) TableLayout() tui.TableLayout {
	return tui.TableLayout{Width: out.TerminalWidth(), Full: out.full}
}

// outputIsTerminal reports whether this boundary writes to a real terminal.
// Colour eligibility follows the output stream, because a redirected stdout
// cannot render escape sequences even when stdin is an interactive terminal.
func (out terminalOutput) outputIsTerminal() bool {
	file, ok := out.Writer.(interface{ Fd() uintptr })
	if !ok {
		return false
	}
	return term.IsTerminal(int(file.Fd()))
}

// resolveOutputColor resolves the colour policy from the output stream. The
// output stream decides eligibility, because escape sequences are written there;
// stdin being a terminal says nothing about whether stdout can render them.
func resolveOutputColor(output io.Writer, noColorFlag bool) tui.ColorPolicy {
	boundary := terminalOutput{Writer: output}
	return tui.ResolveColorPolicy(boundary.outputIsTerminal(), noColorPresent(), noColorFlag, strings.EqualFold(os.Getenv("TERM"), "dumb"), true)
}

// interactiveEditor enables editing only for actual terminals with cancellable reads.
// It returns the editor itself rather than only its ReadLine method, because the
// auto-refresh loop needs the tick-capable reader from the same editor. Returning
// a nil editor means editing is unavailable, and the caller must fall back to the
// plain prompt reader.
func interactiveEditor(input io.Reader, output io.Writer) (*tui.TerminalEditor, func() error, error) {
	file, ok := input.(*os.File)
	if !ok || !term.IsTerminal(int(file.Fd())) {
		return nil, func() error { return nil }, nil
	}
	out := output.(terminalOutput)
	outFile, ok := out.Writer.(*os.File)
	if !ok || !term.IsTerminal(int(outFile.Fd())) || os.Getenv("TERM") == "dumb" {
		return nil, func() error { return nil }, nil
	}
	fd := int(file.Fd())
	owned, err := os.OpenFile(file.Name(), os.O_RDONLY, 0)
	if err != nil {
		return nil, nil, fmt.Errorf("open terminal editor: %w", err)
	}
	// Never call owned.Fd: it disables polling on the deadline reader.
	if err := owned.SetReadDeadline(time.Time{}); err != nil {
		closeErr := owned.Close()
		if closeErr != nil {
			return nil, nil, closeErr
		}
		return nil, func() error { return nil }, nil
	}
	editor := tui.NewTerminalEditor(owned, out, out.TerminalWidth, func() (func() error, error) {
		state, err := term.MakeRaw(fd)
		if err != nil {
			return nil, err
		}
		return func() error { return term.Restore(fd, state) }, nil
	})
	return editor, owned.Close, nil
}

// wireEditorReaders attaches both readers from one editor. A nil editor keeps the
// plain prompt reader, so watch refuses explicitly instead of silently degrading
// to a single read. This is a separate function so a test can prove the shipped
// wiring provides the tick-capable reader, which unit tests that inject the reader
// directly cannot prove.
func wireEditorReaders(options tui.InteractiveOptions, editor *tui.TerminalEditor) tui.InteractiveOptions {
	if editor == nil {
		return options
	}
	options.ReadLine = editor.ReadLine
	options.WatchReader = editor
	return options
}
