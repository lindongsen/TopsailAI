package harness

import (
	"errors"
	"net"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

func TestFreePortEReportsInvalidAddress(t *testing.T) {
	if _, err := freePortAtE("127.0.0.1:not-a-port"); err == nil {
		t.Fatal("freePortAtE unexpectedly accepted an invalid address")
	}
}

func TestFreePortEReportsOccupiedAddress(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	defer listener.Close()
	address := listener.Addr().String()
	if _, err := freePortAtE(address); err == nil {
		t.Fatal("freePortAtE unexpectedly succeeded on an occupied address")
	}
}

func TestCertificatesEReportsUnwritableDirectory(t *testing.T) {
	path := filepath.Join(t.TempDir(), "not-a-directory")
	if err := os.WriteFile(path, []byte("file"), 0o600); err != nil {
		t.Fatal(err)
	}
	if _, err := CertificatesE(path); err == nil {
		t.Fatal("CertificatesE unexpectedly succeeded with a file as its directory")
	} else if !strings.Contains(err.Error(), "create certificate") {
		t.Fatalf("error = %q, want certificate creation context", err)
	}
}

func TestStartProcessEReportsMissingExecutable(t *testing.T) {
	if _, err := StartProcessE(filepath.Join(t.TempDir(), "missing"), nil); err == nil {
		t.Fatal("StartProcessE unexpectedly succeeded")
	} else if !strings.Contains(err.Error(), "start process") {
		t.Fatalf("error = %q, want start context", err)
	}
}

func TestWaitHTTPEReportsTimeout(t *testing.T) {
	if err := WaitHTTPE("http://127.0.0.1:1/healthz", "", 200, 30*time.Millisecond); err == nil {
		t.Fatal("WaitHTTPE unexpectedly succeeded")
	} else if !strings.Contains(err.Error(), "before deadline") {
		t.Fatalf("error = %q, want deadline context", err)
	}
}

func TestStartClusterJSONMarshalFailureReturnsError(t *testing.T) {
	original := marshalAdapterConfigurationFn
	marshalAdapterConfigurationFn = func(any) ([]byte, error) { return nil, errors.New("injected marshal failure") }
	defer func() { marshalAdapterConfigurationFn = original }()
	cluster, err := StartCluster(t, ClusterOptions{})
	if err == nil {
		t.Fatal("StartCluster unexpectedly succeeded")
	}
	if cluster != nil {
		t.Fatal("StartCluster returned a cluster after marshal failure")
	}
	if !strings.Contains(err.Error(), "marshal adapter configuration") {
		t.Fatalf("error = %q, want marshal context", err)
	}
}

func TestRequestEReportsUnavailableServer(t *testing.T) {
	listener, err := net.Listen("tcp", "127.0.0.1:0")
	if err != nil {
		t.Fatal(err)
	}
	port := listener.Addr().(*net.TCPAddr).Port
	if err := listener.Close(); err != nil {
		t.Fatal(err)
	}
	cluster := &Cluster{API: strconv.Itoa(port)}
	if _, _, err := cluster.RequestE("GET", "/healthz", nil); err == nil {
		t.Fatal("RequestE unexpectedly succeeded")
	} else {
		message := err.Error()
		if !strings.Contains(message, "send request") || !strings.Contains(message, "healthz") || !strings.Contains(message, "connection refused") {
			t.Fatalf("error = %q, want request context, healthz, and connection refusal", message)
		}
	}
}

func TestRestartEndpointEReportsMissingEndpoint(t *testing.T) {
	cluster := &Cluster{}
	if err := cluster.RestartEndpointE(); err == nil {
		t.Fatal("RestartEndpointE unexpectedly succeeded")
	} else if !strings.Contains(err.Error(), "endpoint process is not running") {
		t.Fatalf("error = %q, want missing endpoint context", err)
	}
	if cluster.Endpoint != nil {
		t.Fatal("RestartEndpointE changed endpoint state after missing endpoint failure")
	}
}

func TestWaitForBeforeInvocationCrashEReportsTimeout(t *testing.T) {
	cluster := &Cluster{EndpointDB: filepath.Join(t.TempDir(), "endpoint.db")}
	start := time.Now()
	if err := cluster.WaitForBeforeInvocationCrashE(30 * time.Millisecond); err == nil {
		t.Fatal("WaitForBeforeInvocationCrashE unexpectedly succeeded")
	} else {
		if !strings.Contains(err.Error(), "before deadline") || !strings.Contains(err.Error(), "crash marker") {
			t.Fatalf("error = %q, want crash-marker deadline context", err)
		}
		if elapsed := time.Since(start); elapsed < 30*time.Millisecond {
			t.Fatalf("wait returned after %s, want at least 30ms", elapsed)
		}
	}
}

func TestExpectedEndpointExitClassification(t *testing.T) {
	tests := []struct {
		name string
		err  error
		want bool
	}{
		{name: "expected exit 98", err: exitErrorForTest(t, 98), want: true},
		{name: "expected exit minus one", err: exitErrorForTest(t, -1), want: true},
		{name: "unexpected exit 1", err: exitErrorForTest(t, 1), want: false},
		{name: "non exit error", err: errors.New("wait failed"), want: false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			if got := expectedEndpointExit(tt.err); got != tt.want {
				t.Fatalf("expectedEndpointExit(%v) = %t, want %t", tt.err, got, tt.want)
			}
		})
	}
}

func exitErrorForTest(t *testing.T, code int) error {
	t.Helper()
	if code == -1 {
		cmd := exec.Command("sh", "-c", "kill -TERM $$")
		if err := cmd.Run(); err == nil {
			t.Fatal("signal command unexpectedly exited successfully")
		} else {
			return err
		}
	}
	return runExitCommand(t, code)
}

func runExitCommand(t *testing.T, code int) error {
	t.Helper()
	cmd := exec.Command("sh", "-c", "exit "+strconv.Itoa(code))
	if err := cmd.Run(); err == nil {
		t.Fatalf("command unexpectedly exited successfully with code %d", code)
	} else {
		return err
	}
	return nil
}
