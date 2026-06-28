package main

import (
	"testing"
)

func TestParseGroupCreateArgs(t *testing.T) {
	tests := []struct {
		name            string
		args            []string
		wantName        string
		wantContext     string
		wantKey         string
		wantInteractive bool
		wantErr         bool
	}{
		{
			name:            "empty args triggers interactive",
			args:            []string{},
			wantInteractive: true,
		},
		{
			name:     "positional name only",
			args:     []string{"MyGroup"},
			wantName: "MyGroup",
		},
		{
			name:        "positional name and context",
			args:        []string{"MyGroup", "Some context"},
			wantName:    "MyGroup",
			wantContext: "Some context",
		},
		{
			name:        "positional name context key",
			args:        []string{"MyGroup", "Some context", "secret-key"},
			wantName:    "MyGroup",
			wantContext: "Some context",
			wantKey:     "secret-key",
		},
		{
			name:     "flag name only",
			args:     []string{"--name", "FlagGroup"},
			wantName: "FlagGroup",
		},
		{
			name:        "flag name equals syntax",
			args:        []string{"--name=EqGroup", "--context=Ctx", "--key=K"},
			wantName:    "EqGroup",
			wantContext: "Ctx",
			wantKey:     "K",
		},
		{
			name:        "flag style full",
			args:        []string{"--name", "FlagGroup", "--context", "Flag context", "--key", "flag-key"},
			wantName:    "FlagGroup",
			wantContext: "Flag context",
			wantKey:     "flag-key",
		},
		{
			name:        "mixed positional and flags flags win",
			args:        []string{"PosGroup", "--context", "FlagCtx", "pos-key"},
			wantName:    "PosGroup",
			wantContext: "FlagCtx",
			wantKey:     "pos-key",
		},
		{
			name:    "unknown flag",
			args:    []string{"--unknown", "value"},
			wantErr: true,
		},
		{
			name:    "flag missing value",
			args:    []string{"--name"},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			name, ctx, key, needInteractive, err := parseGroupCreateArgs(tt.args)
			if (err != nil) != tt.wantErr {
				t.Fatalf("parseGroupCreateArgs() error = %v, wantErr %v", err, tt.wantErr)
			}
			if err != nil {
				return
			}
			if name != tt.wantName {
				t.Errorf("name = %q, want %q", name, tt.wantName)
			}
			if ctx != tt.wantContext {
				t.Errorf("context = %q, want %q", ctx, tt.wantContext)
			}
			if key != tt.wantKey {
				t.Errorf("key = %q, want %q", key, tt.wantKey)
			}
			if needInteractive != tt.wantInteractive {
				t.Errorf("needInteractive = %v, want %v", needInteractive, tt.wantInteractive)
			}
		})
	}
}
