// Package main provides unit tests for CLI entry helpers.
package main

import (
	"os"
	"testing"
)

func TestResolveInitialAuth(t *testing.T) {
	tests := []struct {
		name       string
		apiKey     string
		sessionKey string
		wantMethod AuthMethod
		wantValue  string
	}{
		{
			name:       "session takes precedence",
			apiKey:     "ak-xxx.yyy",
			sessionKey: "session-123",
			wantMethod: AuthMethodSession,
			wantValue:  "session-123",
		},
		{
			name:       "api key when session empty",
			apiKey:     "ak-xxx.yyy",
			sessionKey: "",
			wantMethod: AuthMethodAPIKey,
			wantValue:  "ak-xxx.yyy",
		},
		{
			name:       "empty when both empty",
			apiKey:     "",
			sessionKey: "",
			wantMethod: "",
			wantValue:  "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			method, value := resolveInitialAuth(tt.apiKey, tt.sessionKey)
			if method != tt.wantMethod {
				t.Errorf("method = %q, want %q", method, tt.wantMethod)
			}
			if value != tt.wantValue {
				t.Errorf("value = %q, want %q", value, tt.wantValue)
			}
		})
	}
}

func TestGetEnv(t *testing.T) {
	key := "ACS_CLI_TEST_GETENV"
	_ = os.Unsetenv(key)

	if got := getEnv(key, "default"); got != "default" {
		t.Errorf("getEnv unset = %q, want %q", got, "default")
	}

	_ = os.Setenv(key, "override")
	defer os.Unsetenv(key)

	if got := getEnv(key, "default"); got != "override" {
		t.Errorf("getEnv set = %q, want %q", got, "override")
	}
}
