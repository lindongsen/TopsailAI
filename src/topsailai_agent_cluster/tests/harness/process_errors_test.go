package harness

import (
	"errors"
	"net"
	"os"
	"path/filepath"
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
