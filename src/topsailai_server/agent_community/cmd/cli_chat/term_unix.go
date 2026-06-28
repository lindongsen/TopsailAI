//go:build !windows
// +build !windows

// Package main provides terminal helpers for Unix-like systems.
package main

import (
	"os"
	"syscall"

	"golang.org/x/sys/unix"
)

// getTermSize returns the terminal width and height.
func getTermSize() (int, int, error) {
	ws, err := unix.IoctlGetWinsize(int(os.Stdout.Fd()), syscall.TIOCGWINSZ)
	if err != nil {
		return 80, 24, err
	}
	return int(ws.Col), int(ws.Row), nil
}
