package protocol

import (
	"strings"
	"testing"
)

func TestCommandExecRequestValidateAcceptsArgv(t *testing.T) {
	request := CommandExecRequest{Argv: []string{"git", "status", "--short"}}
	if err := request.Validate(); err != nil {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestCommandExecRequestValidateRejectsEmptyArgv(t *testing.T) {
	request := CommandExecRequest{}
	if err := request.Validate(); err == nil {
		t.Fatal("expected an error for an empty argv")
	}
}

func TestCommandExecRequestValidateRejectsEmptyToken(t *testing.T) {
	request := CommandExecRequest{Argv: []string{"git", ""}}
	if err := request.Validate(); err == nil {
		t.Fatal("expected an error for an empty token")
	}
}

func TestCommandExecRequestValidateRejectsControlCharacters(t *testing.T) {
	request := CommandExecRequest{Argv: []string{"git", "status\nrm -rf /"}}
	err := request.Validate()
	if err == nil {
		t.Fatal("expected an error for a control character")
	}
	if !strings.Contains(err.Error(), "control characters") {
		t.Fatalf("unexpected error: %v", err)
	}
}

func TestCommandExecRequestValidateRejectsOversizedToken(t *testing.T) {
	request := CommandExecRequest{Argv: []string{"git", strings.Repeat("a", CommandExecMaxTokenBytes+1)}}
	if err := request.Validate(); err == nil {
		t.Fatal("expected an error for an oversized token")
	}
}

func TestCommandExecRequestValidateRejectsTooManyTokens(t *testing.T) {
	argv := make([]string, CommandExecMaxArgv+1)
	for index := range argv {
		argv[index] = "a"
	}
	request := CommandExecRequest{Argv: argv}
	if err := request.Validate(); err == nil {
		t.Fatal("expected an error for too many tokens")
	}
}

// TestCommandExecRequestValidateKeepsShellMetacharactersLiteral proves the
// payload validator does not reject shell metacharacters. They are inert
// because execution never invokes a shell, and rejecting them would imply the
// Endpoint parses a command string, which it must not do.
func TestCommandExecRequestValidateKeepsShellMetacharactersLiteral(t *testing.T) {
	request := CommandExecRequest{Argv: []string{"git", "log", "--grep=$(id)", "a;b", "c|d"}}
	if err := request.Validate(); err != nil {
		t.Fatalf("shell metacharacters must stay literal, got error: %v", err)
	}
}
