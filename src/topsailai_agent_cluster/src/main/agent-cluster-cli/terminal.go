package main

import (
	"io"

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
