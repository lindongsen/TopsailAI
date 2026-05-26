package main

import (
	"encoding/json"
	"flag"
	"net/http"
	"net/http/httptest"
	"os"
	"testing"
)

func TestBaseURL_Default(t *testing.T) {
	cfg := &Config{APIBase: ""}
	got := cfg.baseURL()
	want := "http://localhost:7373/api/v1"
	if got != want {
		t.Errorf("baseURL() = %q, want %q", got, want)
	}
}

func TestBaseURL_PlainHostPort(t *testing.T) {
	cfg := &Config{APIBase: "http://172.18.0.4:7373"}
	got := cfg.baseURL()
	want := "http://172.18.0.4:7373/api/v1"
	if got != want {
		t.Errorf("baseURL() = %q, want %q", got, want)
	}
}

func TestBaseURL_AlreadySuffixed(t *testing.T) {
	cfg := &Config{APIBase: "http://172.18.0.4:7373/api/v1"}
	got := cfg.baseURL()
	want := "http://172.18.0.4:7373/api/v1"
	if got != want {
		t.Errorf("baseURL() = %q, want %q", got, want)
	}
}

func TestBaseURL_TrailingSlash(t *testing.T) {
	cfg := &Config{APIBase: "http://172.18.0.4:7373/"}
	got := cfg.baseURL()
	want := "http://172.18.0.4:7373/api/v1"
	if got != want {
		t.Errorf("baseURL() = %q, want %q", got, want)
	}
}

func TestRawBaseURL(t *testing.T) {
	cfg := &Config{APIBase: "http://172.18.0.4:7373/api/v1"}
	got := cfg.rawBaseURL()
	want := "http://172.18.0.4:7373"
	if got != want {
		t.Errorf("rawBaseURL() = %q, want %q", got, want)
	}
}

func TestSetAuthHeader_XAPIKey(t *testing.T) {
	cfg := &Config{APIKey: "secret", AuthStyle: "x-api-key"}
	req, _ := http.NewRequest("GET", "http://example.com", nil)
	cfg.setAuthHeader(req)
	got := req.Header.Get("X-API-Key")
	want := "secret"
	if got != want {
		t.Errorf("X-API-Key = %q, want %q", got, want)
	}
}

func TestSetAuthHeader_Bearer(t *testing.T) {
	cfg := &Config{APIKey: "secret", AuthStyle: "bearer"}
	req, _ := http.NewRequest("GET", "http://example.com", nil)
	cfg.setAuthHeader(req)
	got := req.Header.Get("Authorization")
	want := "Bearer secret"
	if got != want {
		t.Errorf("Authorization = %q, want %q", got, want)
	}
}

func TestSetAuthHeader_EmptyKey(t *testing.T) {
	cfg := &Config{APIKey: ""}
	req, _ := http.NewRequest("GET", "http://example.com", nil)
	cfg.setAuthHeader(req)
	if req.Header.Get("X-API-Key") != "" {
		t.Error("expected no X-API-Key header for empty APIKey")
	}
	if req.Header.Get("Authorization") != "" {
		t.Error("expected no Authorization header for empty APIKey")
	}
}

func TestHandleHealthCommand_Success(t *testing.T) {
	respBody := APIResponse{Code: 0, Data: json.RawMessage(`{"status":"healthy"}`), Message: "OK"}
	respBytes, _ := json.Marshal(respBody)

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/health" {
			t.Errorf("expected path /health, got %s", r.URL.Path)
		}
		w.WriteHeader(http.StatusOK)
		w.Write(respBytes)
	}))
	defer ts.Close()

	cfg := &Config{APIBase: ts.URL}
	err := handleHealthCommand(cfg)
	if err != nil {
		t.Errorf("handleHealthCommand() error = %v", err)
	}
}

func TestHandleHealthCommand_Failure(t *testing.T) {
	respBody := APIResponse{Code: 1, Message: "unhealthy"}
	respBytes, _ := json.Marshal(respBody)

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write(respBytes)
	}))
	defer ts.Close()

	cfg := &Config{APIBase: ts.URL}
	err := handleHealthCommand(cfg)
	if err == nil {
		t.Error("handleHealthCommand() expected error, got nil")
	}
}

func TestHandleStatusCommand_Success(t *testing.T) {
	respBody := APIResponse{
		Code:    0,
		Data:    json.RawMessage(`{"status":"idle","session_id":"test-session"}`),
		Message: "OK",
	}
	respBytes, _ := json.Marshal(respBody)

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		expectedPath := "/api/v1/session/test-session"
		if r.URL.Path != expectedPath {
			t.Errorf("expected path %s, got %s", expectedPath, r.URL.Path)
		}
		w.WriteHeader(http.StatusOK)
		w.Write(respBytes)
	}))
	defer ts.Close()

	cfg := &Config{APIBase: ts.URL, SessionID: "test-session"}
	err := handleStatusCommand(cfg)
	if err != nil {
		t.Errorf("handleStatusCommand() error = %v", err)
	}
}

func TestHandleStatusCommand_MissingSessionID(t *testing.T) {
	cfg := &Config{APIBase: "http://localhost:7373", SessionID: ""}
	err := handleStatusCommand(cfg)
	if err == nil {
		t.Error("handleStatusCommand() expected error for missing session-id, got nil")
	}
}

func TestHandleStatusCommand_APIError(t *testing.T) {
	respBody := APIResponse{Code: 1, Message: "session not found"}
	respBytes, _ := json.Marshal(respBody)

	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
		w.Write(respBytes)
	}))
	defer ts.Close()

	cfg := &Config{APIBase: ts.URL, SessionID: "bad-session"}
	err := handleStatusCommand(cfg)
	if err == nil {
		t.Error("handleStatusCommand() expected error, got nil")
	}
}

func TestLoadConfig_DEBUG_Zero(t *testing.T) {
	os.Setenv("DEBUG", "0")
	defer os.Unsetenv("DEBUG")

	// Save and restore os.Args
	oldArgs := os.Args
	defer func() { os.Args = oldArgs }()
	os.Args = []string{"cmd", "-message", "hello"}

	// Reset flags for clean parse
	flag.CommandLine = flag.NewFlagSet(os.Args[0], flag.ContinueOnError)

	cfg := loadConfig()
	if !cfg.ResultOnly {
		t.Errorf("DEBUG=0 should set ResultOnly=true, got %v", cfg.ResultOnly)
	}
}

func TestLoadConfig_DEBUG_One(t *testing.T) {
	os.Setenv("DEBUG", "1")
	defer os.Unsetenv("DEBUG")

	oldArgs := os.Args
	defer func() { os.Args = oldArgs }()
	os.Args = []string{"cmd", "-message", "hello"}

	flag.CommandLine = flag.NewFlagSet(os.Args[0], flag.ContinueOnError)

	cfg := loadConfig()
	if cfg.ResultOnly {
		t.Errorf("DEBUG=1 should set ResultOnly=false, got %v", cfg.ResultOnly)
	}
}

func TestLoadConfig_DEBUG_Unset_ResultOnly_True(t *testing.T) {
	os.Unsetenv("DEBUG")
	os.Setenv("RESULT_ONLY", "true")
	defer os.Unsetenv("RESULT_ONLY")

	oldArgs := os.Args
	defer func() { os.Args = oldArgs }()
	os.Args = []string{"cmd", "-message", "hello"}

	flag.CommandLine = flag.NewFlagSet(os.Args[0], flag.ContinueOnError)

	cfg := loadConfig()
	if !cfg.ResultOnly {
		t.Errorf("RESULT_ONLY=true should set ResultOnly=true, got %v", cfg.ResultOnly)
	}
}

func TestLoadConfig_DEBUG_Unset_ResultOnly_False(t *testing.T) {
	os.Unsetenv("DEBUG")
	os.Unsetenv("RESULT_ONLY")

	oldArgs := os.Args
	defer func() { os.Args = oldArgs }()
	os.Args = []string{"cmd", "-message", "hello"}

	flag.CommandLine = flag.NewFlagSet(os.Args[0], flag.ContinueOnError)

	cfg := loadConfig()
	if cfg.ResultOnly {
		t.Errorf("default should set ResultOnly=false, got %v", cfg.ResultOnly)
	}
}
