// Package main provides readline-based input for the ACS chat CLI.
package main

import (
	"io"

	"github.com/chzyer/readline"
)

// lineReader abstracts command-line input reading.
type lineReader interface {
	ReadLine() (string, error)
	Close() error
}

// readlineReader wraps a readline.Instance.
type readlineReader struct {
	inst *readline.Instance
}

// newReadlineReader creates a readline-based line reader.
func newReadlineReader(prompt *PromptManager, completer *Completer, userName string, group *Group) (*readlineReader, error) {
	prompt.SetUser(userName)
	groupID := ""
	if group != nil {
		groupID = group.GroupID
	}
	prompt.SetGroup(groupID)

	cfg := &readline.Config{
		Prompt:          prompt.Prompt(),
		AutoComplete:    completer,
		InterruptPrompt: "^C",
		EOFPrompt:       "exit",
	}
	inst, err := readline.NewEx(cfg)
	if err != nil {
		return nil, err
	}
	return &readlineReader{inst: inst}, nil
}

// ReadLine reads a single line of input.
func (r *readlineReader) ReadLine() (string, error) {
	line, err := r.inst.Readline()
	if err == readline.ErrInterrupt {
		return "", io.EOF
	}
	return line, err
}

// Close closes the underlying readline instance.
func (r *readlineReader) Close() error {
	return r.inst.Close()
}

// SetPrompt updates the prompt string.
func (r *readlineReader) SetPrompt(p string) {
	r.inst.SetPrompt(p)
}
