//go:build windows
// +build windows

// Package main provides terminal helpers for Windows.
package main

// getTermSize returns a default terminal size on Windows.
func getTermSize() (int, int, error) {
	return 120, 30, nil
}
