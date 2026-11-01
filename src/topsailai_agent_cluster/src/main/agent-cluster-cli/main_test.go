package main

import (
	"strings"
	"testing"
)

func TestInteractiveRejectsNonTerminalBeforeNetwork(t *testing.T) {
	err := runWithIO([]string{"--server-url", "http://127.0.0.1:1", "interactive"}, strings.NewReader("quit\n"), &strings.Builder{}, &strings.Builder{}, false)
	if err == nil || err.Error() != "interactive mode requires a terminal on stdin" {
		t.Fatalf("unexpected non-terminal result: %v", err)
	}
}
