package main

import (
	"fmt"
	"io"
	"os"
	"time"
	"topsailai_agent_cluster/internal/tui"

	"golang.org/x/term"
)

// terminalOutput exposes the actual output terminal size, including after resize.
type terminalOutput struct{ io.Writer }

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

// interactiveEditor enables editing only for actual terminals with cancellable reads.
func interactiveEditor(input io.Reader, output io.Writer) (tui.InteractiveLineReader, func() error, error) {
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
	return editor.ReadLine, owned.Close, nil
}
