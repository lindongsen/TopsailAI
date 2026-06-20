package main

import (
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestParseArgs_Empty(t *testing.T) {
	cmd, isDaemon, err := parseArgs(nil)
	assert.NoError(t, err)
	assert.Equal(t, "", cmd)
	assert.False(t, isDaemon)
}

func TestParseArgs_Commands(t *testing.T) {
	tests := []struct {
		name       string
		args       []string
		wantCmd    string
		wantDaemon bool
		wantErr    bool
	}{
		{"start", []string{"start"}, "start", true, false},
		{"stop", []string{"stop"}, "stop", false, false},
		{"restart", []string{"restart"}, "restart", false, false},
		{"status", []string{"status"}, "status", false, false},
		{"help", []string{"help"}, "help", false, false},
		{"short help", []string{"-h"}, "help", false, false},
		{"long help", []string{"--help"}, "help", false, false},
		{"daemon internal short", []string{"-d"}, "daemon-internal", true, false},
		{"daemon internal long", []string{"--daemon-internal"}, "daemon-internal", true, false},
		{"unknown", []string{"foo"}, "", false, true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cmd, isDaemon, err := parseArgs(tt.args)
			if tt.wantErr {
				assert.Error(t, err)
				return
			}
			assert.NoError(t, err)
			assert.Equal(t, tt.wantCmd, cmd)
			assert.Equal(t, tt.wantDaemon, isDaemon)
		})
	}
}
