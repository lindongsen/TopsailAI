// Package main provides unit tests for tab auto-completion.
package main

import (
	"testing"
)

func TestNewNormalCompleterNotNil(t *testing.T) {
	c := newNormalCompleter()
	if c == nil {
		t.Fatal("newNormalCompleter() returned nil")
	}
}

func TestNewChatCompleterNotNil(t *testing.T) {
	c := newChatCompleter()
	if c == nil {
		t.Fatal("newChatCompleter() returned nil")
	}
}

func TestFilterCommands(t *testing.T) {
	commands := []string{
		"/group:list", "/group:create", "/group:enter",
		"/member:list", "/member:add",
		"/message:list",
		"/help", "/exit",
	}

	tests := []struct {
		prefix string
		want   []string
	}{
		{"/g", []string{"/group:list", "/group:create", "/group:enter"}},
		{"/group:", []string{"/group:list", "/group:create", "/group:enter"}},
		{"/mes", []string{"/message:list"}},
		{"/mem", []string{"/member:list", "/member:add"}},
		{"/h", []string{"/help"}},
		{"/ex", []string{"/exit"}},
		{"/xyz", []string{}},
		{"", commands},
	}

	for _, tt := range tests {
		t.Run(tt.prefix, func(t *testing.T) {
			got := filterCommands(tt.prefix, commands)
			if len(got) != len(tt.want) {
				t.Fatalf("filterCommands(%q) = %v, want %v", tt.prefix, got, tt.want)
			}
			for i := range tt.want {
				if got[i] != tt.want[i] {
					t.Errorf("filterCommands(%q)[%d] = %q, want %q", tt.prefix, i, got[i], tt.want[i])
				}
			}
		})
	}
}

func TestFilterCommandsCaseInsensitive(t *testing.T) {
	commands := []string{"/group:list", "/GROUP:create"}

	got := filterCommands("/GROUP", commands)
	if len(got) != 2 {
		t.Errorf("expected 2 matches for case-insensitive filter, got %d", len(got))
	}
}

func TestCompleterFromCommands(t *testing.T) {
	commands := []string{"/foo", "/bar", "/baz"}
	c := completerFromCommands(commands)
	if c == nil {
		t.Fatal("completerFromCommands() returned nil")
	}

	for _, cmd := range commands {
		_, _ = c.Do([]rune(cmd), len(cmd))
	}
}

func TestNormalCompleterDoDoesNotPanic(t *testing.T) {
	c := newNormalCompleter()
	inputs := []string{"/mes", "he", "/mem", "/group", "/", "exit", "quit", "help"}
	for _, input := range inputs {
		_, _ = c.Do([]rune(input), len(input))
	}
}

func TestChatCompleterDoDoesNotPanic(t *testing.T) {
	c := newChatCompleter()
	inputs := []string{"/mem", "/ex", "/h", "/", "exit", "quit"}
	for _, input := range inputs {
		_, _ = c.Do([]rune(input), len(input))
	}
}
