// Package main provides integration-style tests that exercise the compiled
// acs-cli binary to verify end-to-end behavior such as authentication header
// transmission.
package main

import (
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"path/filepath"
	"runtime"
	"strings"
	"testing"
	"time"
)

// findCLIBinary returns the path to the compiled acs-cli binary, building it
// first if necessary.
func findCLIBinary(t *testing.T) string {
	t.Helper()

	// Determine repository root from this test file location.
	_, testFile, _, ok := runtime.Caller(0)
	if !ok {
		t.Fatal("failed to determine test file path")
	}
	repoRoot := filepath.Join(filepath.Dir(testFile), "..", "..")
	repoRoot, err := filepath.Abs(repoRoot)
	if err != nil {
		t.Fatalf("failed to resolve repo root: %v", err)
	}

	binary := filepath.Join(repoRoot, "bin", "acs-cli")

	// Build the binary if it does not exist or is older than the source.
	srcPattern := filepath.Join(repoRoot, "cmd", "cli", "*.go")
	needsBuild := false
	if _, err := os.Stat(binary); err != nil {
		needsBuild = true
	} else {
		binInfo, _ := os.Stat(binary)
		srcFiles, err := filepath.Glob(srcPattern)
		if err != nil {
			t.Fatalf("failed to glob source files: %v", err)
		}
		for _, sf := range srcFiles {
			fi, err := os.Stat(sf)
			if err != nil {
				continue
			}
			if fi.ModTime().After(binInfo.ModTime()) {
				needsBuild = true
				break
			}
		}
	}

	if needsBuild {
		cmd := exec.Command("go", "build", "-o", binary, "./cmd/cli")
		cmd.Dir = repoRoot
		out, err := cmd.CombinedOutput()
		if err != nil {
			t.Fatalf("failed to build acs-cli: %v\n%s", err, out)
		}
	}

	return binary
}

// TestCLIBinary_SendsSessionKeyHeader verifies that the compiled acs-cli binary
// sends the X-Session-Key header when started with -session-key.
func TestCLIBinary_SendsSessionKeyHeader(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping binary integration test in short mode")
	}

	receivedHeaders := make(chan http.Header, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		// Capture the headers for the first API request we see.
		select {
		case receivedHeaders <- r.Header:
		default:
		}

		// Return a successful account response for /api/v1/accounts/me so the
		// CLI initialization handshake completes.
		if strings.HasPrefix(r.URL.Path, "/api/v1/accounts/me") {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"data":{"account_id":"acc-test","account_name":"Test","role":"user","status":"active","login_name":"test@example.com","create_at_ms":1704067200000,"update_at_ms":1704067200000},"trace_id":"trace-1"}`))
			return
		}

		// Default success for other endpoints.
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{},"trace_id":"trace-1"}`))
	}))
	defer server.Close()

	binary := findCLIBinary(t)

	cmd := exec.Command(binary,
		"-api-base", server.URL,
		"-session-key", "acc-test-VALIDSECRET",
	)
	cmd.Stdin = strings.NewReader("/account:me\n/exit\n")
	cmd.Stdout = io.Discard
	cmd.Stderr = io.Discard

	if err := cmd.Start(); err != nil {
		t.Fatalf("failed to start acs-cli: %v", err)
	}

	// Wait for the request to be received or the process to exit.
	var headers http.Header
	select {
	case headers = <-receivedHeaders:
	case <-time.After(10 * time.Second):
		t.Fatal("timed out waiting for CLI request")
	}

	_ = cmd.Wait()

	sessionKey := headers.Get("X-Session-Key")
	if sessionKey == "" {
		t.Fatalf("X-Session-Key header not sent; received headers: %v", headers)
	}
	if sessionKey != "acc-test-VALIDSECRET" {
		t.Fatalf("X-Session-Key = %q, want %q", sessionKey, "acc-test-VALIDSECRET")
	}
}

// TestCLIBinary_SendsAPIKeyHeader verifies that the compiled acs-cli binary
// sends the Authorization header when started with -api-key.
func TestCLIBinary_SendsAPIKeyHeader(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping binary integration test in short mode")
	}

	receivedHeaders := make(chan http.Header, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case receivedHeaders <- r.Header:
		default:
		}

		if strings.HasPrefix(r.URL.Path, "/api/v1/accounts/me") {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"data":{"account_id":"acc-test","account_name":"Test","role":"user","status":"active","login_name":"test@example.com","create_at_ms":1704067200000,"update_at_ms":1704067200000},"trace_id":"trace-1"}`))
			return
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{},"trace_id":"trace-1"}`))
	}))
	defer server.Close()

	binary := findCLIBinary(t)

	cmd := exec.Command(binary,
		"-api-base", server.URL,
		"-api-key", "ak-test.secretvalue",
	)
	cmd.Stdin = strings.NewReader("/account:me\n/exit\n")
	cmd.Stdout = io.Discard
	cmd.Stderr = io.Discard

	if err := cmd.Start(); err != nil {
		t.Fatalf("failed to start acs-cli: %v", err)
	}

	var headers http.Header
	select {
	case headers = <-receivedHeaders:
	case <-time.After(10 * time.Second):
		t.Fatal("timed out waiting for CLI request")
	}

	_ = cmd.Wait()

	authz := headers.Get("Authorization")
	if authz == "" {
		t.Fatalf("Authorization header not sent; received headers: %v", headers)
	}
	want := "Bearer ak-test.secretvalue"
	if authz != want {
		t.Fatalf("Authorization = %q, want %q", authz, want)
	}
}

// TestCLIBinary_InteractiveLoginSessionKey verifies that an interactive
// /login session-key=... command sends the X-Session-Key header on the next
// request.
func TestCLIBinary_InteractiveLoginSessionKey(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping binary integration test in short mode")
	}

	receivedHeaders := make(chan http.Header, 2)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case receivedHeaders <- r.Header:
		default:
		}

		if strings.HasPrefix(r.URL.Path, "/api/v1/accounts/me") {
			w.Header().Set("Content-Type", "application/json")
			_, _ = w.Write([]byte(`{"data":{"account_id":"acc-test","account_name":"Test","role":"user","status":"active","login_name":"test@example.com","create_at_ms":1704067200000,"update_at_ms":1704067200000},"trace_id":"trace-1"}`))
			return
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{},"trace_id":"trace-1"}`))
	}))
	defer server.Close()

	binary := findCLIBinary(t)

	cmd := exec.Command(binary, "-api-base", server.URL)
	cmd.Stdin = strings.NewReader("/login session-key=acc-test-VALIDSECRET\n/account:me\n/exit\n")
	cmd.Stdout = io.Discard
	cmd.Stderr = io.Discard

	if err := cmd.Start(); err != nil {
		t.Fatalf("failed to start acs-cli: %v", err)
	}

	// Collect up to two requests: the GetMe during /login and the /account:me.
	var headers []http.Header
	timeout := time.After(10 * time.Second)
	for len(headers) < 2 {
		select {
		case h := <-receivedHeaders:
			headers = append(headers, h)
		case <-timeout:
			t.Fatal("timed out waiting for CLI requests")
		}
	}

	_ = cmd.Wait()

	// The second request should be /account:me and must include the header.
	last := headers[len(headers)-1]
	sessionKey := last.Get("X-Session-Key")
	if sessionKey == "" {
		t.Fatalf("X-Session-Key header not sent after interactive login; received headers: %v", last)
	}
	if sessionKey != "acc-test-VALIDSECRET" {
		t.Fatalf("X-Session-Key = %q, want %q", sessionKey, "acc-test-VALIDSECRET")
	}
}

// TestCLIBinary_NoAuthSendsNoAuthHeaders verifies that starting the CLI without
// credentials does not send auth headers.
func TestCLIBinary_NoAuthSendsNoAuthHeaders(t *testing.T) {
	if testing.Short() {
		t.Skip("skipping binary integration test in short mode")
	}

	receivedHeaders := make(chan http.Header, 1)
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		select {
		case receivedHeaders <- r.Header:
		default:
		}

		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"data":{},"trace_id":"trace-1"}`))
	}))
	defer server.Close()

	binary := findCLIBinary(t)

	cmd := exec.Command(binary, "-api-base", server.URL)
	cmd.Stdin = strings.NewReader("/group:list\n/exit\n")
	cmd.Stdout = io.Discard
	cmd.Stderr = io.Discard

	if err := cmd.Start(); err != nil {
		t.Fatalf("failed to start acs-cli: %v", err)
	}

	var headers http.Header
	select {
	case headers = <-receivedHeaders:
	case <-time.After(10 * time.Second):
		t.Fatal("timed out waiting for CLI request")
	}

	_ = cmd.Wait()

	if headers.Get("X-Session-Key") != "" || headers.Get("Authorization") != "" {
		t.Fatalf("unexpected auth headers sent without credentials: %v", headers)
	}
}

func init() {
	// Silence the default test binary usage message when running the binary
	// tests; this is only relevant if the test binary is invoked directly.
	fmt.Sprintf("")
}
