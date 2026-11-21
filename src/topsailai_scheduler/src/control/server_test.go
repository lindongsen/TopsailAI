package control

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"log/slog"
	"net"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"topsailai_scheduler/runtime"
)

// fakeController is a runtime.Controller whose answers are fixed, so the
// transport can be tested without the daemon.
type fakeController struct {
	launchResult runtime.LaunchResult
	launchErr    error
	snapshot     runtime.Snapshot
	statusErr    error
	stopResult   runtime.StopResult
	stopErr      error

	// lastLaunch and lastStop record what the transport passed through.
	lastLaunch runtime.LaunchRequest
	lastStop   runtime.StopRequest
}

// Launch implements runtime.Controller.
func (f *fakeController) Launch(request runtime.LaunchRequest) (runtime.LaunchResult, error) {
	f.lastLaunch = request
	return f.launchResult, f.launchErr
}

// Status implements runtime.Controller.
func (f *fakeController) Status() (runtime.Snapshot, error) {
	return f.snapshot, f.statusErr
}

// Stop implements runtime.Controller.
func (f *fakeController) Stop(request runtime.StopRequest) (runtime.StopResult, error) {
	f.lastStop = request
	return f.stopResult, f.stopErr
}

// discardLogger returns a logger that writes nowhere, keeping test output clean.
func discardLogger() *slog.Logger {
	return slog.New(slog.NewTextHandler(io.Discard, nil))
}

// startServer starts a server on a temporary socket and returns the path plus a
// stop function.
func startServer(t *testing.T, controller runtime.Controller) (string, func()) {
	t.Helper()

	socketPath := filepath.Join(t.TempDir(), "control.sock")
	server := NewServer(controller, socketPath, discardLogger())

	ctx, cancel := context.WithCancel(context.Background())
	served := make(chan error, 1)
	go func() { served <- server.Serve(ctx) }()

	// Wait for the socket to accept connections before returning, so the test
	// never races the listener.
	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		connection, err := net.DialTimeout("unix", socketPath, 100*time.Millisecond)
		if err == nil {
			_ = connection.Close()
			break
		}
		time.Sleep(20 * time.Millisecond)
	}

	stop := func() {
		cancel()
		select {
		case <-served:
		case <-time.After(5 * time.Second):
			t.Error("the server did not stop")
		}
		if err := server.Close(); err != nil {
			t.Errorf("Close failed: %v", err)
		}
	}
	return socketPath, stop
}

// TestClientStatusRoundTrip verifies that a status request reaches the
// controller and its snapshot comes back intact.
func TestClientStatusRoundTrip(t *testing.T) {
	controller := &fakeController{
		snapshot: runtime.Snapshot{
			TasksRoot: "/tasks",
			Tasks: []runtime.TaskStatus{
				{ID: "data/work", State: runtime.StateIdle, Schedule: "@daily"},
			},
		},
	}
	socketPath, stop := startServer(t, controller)
	defer stop()

	snapshot, err := NewClient(socketPath).Status()
	if err != nil {
		t.Fatalf("Status failed: %v", err)
	}
	if snapshot.TasksRoot != "/tasks" {
		t.Errorf("unexpected tasks root %q", snapshot.TasksRoot)
	}
	if len(snapshot.Tasks) != 1 || snapshot.Tasks[0].ID != "data/work" {
		t.Errorf("unexpected tasks %+v", snapshot.Tasks)
	}
}

// TestClientLaunchPassesRequest verifies that the launch fields reach the
// controller, so the transport does not drop them.
func TestClientLaunchPassesRequest(t *testing.T) {
	controller := &fakeController{
		launchResult: runtime.LaunchResult{TaskID: "data/work", PID: 1234, TraceID: "trace-1"},
	}
	socketPath, stop := startServer(t, controller)
	defer stop()

	result, err := NewClient(socketPath).Launch(runtime.LaunchRequest{TaskID: "data/work", Wait: true})
	if err != nil {
		t.Fatalf("Launch failed: %v", err)
	}
	if result.PID != 1234 || result.TraceID != "trace-1" {
		t.Errorf("unexpected result %+v", result)
	}
	if controller.lastLaunch.TaskID != "data/work" || !controller.lastLaunch.Wait {
		t.Errorf("the request was not passed through: %+v", controller.lastLaunch)
	}
}

// TestClientStopPassesForce verifies that the force flag survives the wire, so a
// forced stop is not silently downgraded to a graceful one.
func TestClientStopPassesForce(t *testing.T) {
	controller := &fakeController{
		stopResult: runtime.StopResult{TaskID: "data/work", PID: 99, Forced: true},
	}
	socketPath, stop := startServer(t, controller)
	defer stop()

	result, err := NewClient(socketPath).Stop(runtime.StopRequest{TaskID: "data/work", Force: true})
	if err != nil {
		t.Fatalf("Stop failed: %v", err)
	}
	if !result.Forced || result.PID != 99 {
		t.Errorf("unexpected result %+v", result)
	}
	if !controller.lastStop.Force {
		t.Error("expected the force flag to reach the controller")
	}
}

// TestClientReceivesStableErrorCode verifies that a contract error arrives as a
// RemoteError carrying the stable code, so a caller can branch on it.
func TestClientReceivesStableErrorCode(t *testing.T) {
	controller := &fakeController{
		launchErr: runtime.ErrTaskNotFound,
	}
	socketPath, stop := startServer(t, controller)
	defer stop()

	_, err := NewClient(socketPath).Launch(runtime.LaunchRequest{TaskID: "nope"})
	if err == nil {
		t.Fatal("expected an error")
	}

	var remote *RemoteError
	if !errors.As(err, &remote) {
		t.Fatalf("expected a RemoteError, got %T", err)
	}
	if remote.Code != CodeTaskNotFound {
		t.Errorf("expected code %q, got %q", CodeTaskNotFound, remote.Code)
	}
	if !strings.Contains(remote.Error(), CodeTaskNotFound) {
		t.Errorf("expected the code in the message, got %q", remote.Error())
	}
}

// TestClientMapsEveryContractError verifies that each sentinel error keeps its
// own code across the wire, so the mapping is not collapsed to one value.
func TestClientMapsEveryContractError(t *testing.T) {
	cases := map[string]struct {
		err  error
		want string
	}{
		"not found":     {runtime.ErrTaskNotFound, CodeTaskNotFound},
		"not running":   {runtime.ErrTaskNotRunning, CodeTaskNotRunning},
		"disabled":      {runtime.ErrTaskDisabled, CodeTaskDisabled},
		"shutting down": {runtime.ErrShuttingDown, CodeShuttingDown},
		"internal":      {errors.New("boom"), CodeInternal},
	}
	for name, testCase := range cases {
		t.Run(name, func(t *testing.T) {
			controller := &fakeController{stopErr: testCase.err}
			socketPath, stop := startServer(t, controller)
			defer stop()

			_, err := NewClient(socketPath).Stop(runtime.StopRequest{TaskID: "x"})
			var remote *RemoteError
			if !errors.As(err, &remote) {
				t.Fatalf("expected a RemoteError, got %v", err)
			}
			if remote.Code != testCase.want {
				t.Errorf("expected code %q, got %q", testCase.want, remote.Code)
			}
		})
	}
}

// TestServerRejectsMalformedRequest verifies that a bad request line yields the
// invalid_request code instead of a dropped connection.
func TestServerRejectsMalformedRequest(t *testing.T) {
	socketPath, stop := startServer(t, &fakeController{})
	defer stop()

	connection, err := net.Dial("unix", socketPath)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer func() { _ = connection.Close() }()

	if _, err := connection.Write([]byte("not json\n")); err != nil {
		t.Fatalf("write: %v", err)
	}

	response := readResponse(t, connection)
	if response.OK {
		t.Error("expected the request to be rejected")
	}
	if response.Code != CodeInvalidRequest {
		t.Errorf("expected code %q, got %q", CodeInvalidRequest, response.Code)
	}
}

// TestServerRejectsUnknownOp verifies that an unknown operation is reported as
// invalid_request rather than reaching the controller.
func TestServerRejectsUnknownOp(t *testing.T) {
	controller := &fakeController{}
	socketPath, stop := startServer(t, controller)
	defer stop()

	connection, err := net.Dial("unix", socketPath)
	if err != nil {
		t.Fatalf("dial: %v", err)
	}
	defer func() { _ = connection.Close() }()

	if _, err := connection.Write([]byte(`{"op":"restart"}` + "\n")); err != nil {
		t.Fatalf("write: %v", err)
	}

	response := readResponse(t, connection)
	if response.Code != CodeInvalidRequest {
		t.Errorf("expected code %q, got %q", CodeInvalidRequest, response.Code)
	}
	if controller.lastLaunch.TaskID != "" || controller.lastStop.TaskID != "" {
		t.Error("an unknown op must not reach the controller")
	}
}

// TestServerSocketIsOwnerOnly verifies that the socket is not readable by other
// users, because it is a local control channel.
func TestServerSocketIsOwnerOnly(t *testing.T) {
	socketPath, stop := startServer(t, &fakeController{})
	defer stop()

	info, err := os.Stat(socketPath)
	if err != nil {
		t.Fatalf("stat socket: %v", err)
	}
	if info.Mode().Perm() != 0o600 {
		t.Errorf("expected mode 0600, got %o", info.Mode().Perm())
	}
}

// TestServerCloseRemovesSocket verifies that shutdown removes the socket file,
// so a restart is not blocked by a leftover.
func TestServerCloseRemovesSocket(t *testing.T) {
	socketPath, stop := startServer(t, &fakeController{})
	stop()

	if _, err := os.Stat(socketPath); !os.IsNotExist(err) {
		t.Errorf("expected the socket to be removed, got %v", err)
	}
}

// TestServerRefusesLiveSocket verifies that a second server will not steal a
// socket a running scheduler is serving, because that would disconnect its CLI.
func TestServerRefusesLiveSocket(t *testing.T) {
	socketPath, stop := startServer(t, &fakeController{})
	defer stop()

	second := NewServer(&fakeController{}, socketPath, discardLogger())
	err := second.Serve(context.Background())
	if err == nil {
		t.Fatal("expected the second server to refuse a live socket")
	}
	if !strings.Contains(err.Error(), "already in use") {
		t.Errorf("expected an in-use message, got %q", err.Error())
	}
}

// TestServerReplacesStaleSocket verifies that a leftover socket file from a dead
// process is removed, so a restart succeeds.
func TestServerReplacesStaleSocket(t *testing.T) {
	socketPath := filepath.Join(t.TempDir(), "stale.sock")

	// A crashed daemon leaves the socket file behind. Go unlinks the file when a
	// listener closes normally, so unlinking is disabled here to reproduce the
	// leftover state.
	address, err := net.ResolveUnixAddr("unix", socketPath)
	if err != nil {
		t.Fatalf("resolve address: %v", err)
	}
	listener, err := net.ListenUnix("unix", address)
	if err != nil {
		t.Fatalf("listen: %v", err)
	}
	listener.SetUnlinkOnClose(false)
	if err := listener.Close(); err != nil {
		t.Fatalf("close listener: %v", err)
	}
	if _, err := os.Stat(socketPath); err != nil {
		t.Fatalf("expected the stale socket file to exist: %v", err)
	}

	server := NewServer(&fakeController{}, socketPath, discardLogger())
	ctx, cancel := context.WithCancel(context.Background())
	served := make(chan error, 1)
	go func() { served <- server.Serve(ctx) }()

	deadline := time.Now().Add(5 * time.Second)
	for time.Now().Before(deadline) {
		connection, dialErr := net.DialTimeout("unix", socketPath, 100*time.Millisecond)
		if dialErr == nil {
			_ = connection.Close()
			break
		}
		time.Sleep(20 * time.Millisecond)
	}

	cancel()
	select {
	case err := <-served:
		if err != nil {
			t.Fatalf("Serve failed: %v", err)
		}
	case <-time.After(5 * time.Second):
		t.Fatal("the server did not stop")
	}
	if err := server.Close(); err != nil {
		t.Errorf("Close failed: %v", err)
	}
}

// TestServerRejectsNonSocketPath verifies that a regular file at the socket path
// is reported instead of being deleted, because it may be someone's data.
func TestServerRejectsNonSocketPath(t *testing.T) {
	socketPath := filepath.Join(t.TempDir(), "not-a-socket")
	if err := os.WriteFile(socketPath, []byte("data"), 0o644); err != nil {
		t.Fatalf("write file: %v", err)
	}

	server := NewServer(&fakeController{}, socketPath, discardLogger())
	err := server.Serve(context.Background())
	if err == nil {
		t.Fatal("expected a regular file at the socket path to be rejected")
	}
	if !strings.Contains(err.Error(), "not a socket") {
		t.Errorf("expected a not-a-socket message, got %q", err.Error())
	}
	if _, statErr := os.Stat(socketPath); statErr != nil {
		t.Errorf("the existing file must not be deleted: %v", statErr)
	}
}

// TestClientWithoutServerFails verifies that a missing daemon produces a clear
// connection error instead of a hang.
func TestClientWithoutServerFails(t *testing.T) {
	socketPath := filepath.Join(t.TempDir(), "absent.sock")
	_, err := NewClient(socketPath).Status()
	if err == nil {
		t.Fatal("expected an error when no daemon is listening")
	}
	if !strings.Contains(err.Error(), "connect to scheduler") {
		t.Errorf("expected a connection message, got %q", err.Error())
	}
}

// TestWithTimeout verifies that a non-positive timeout keeps the client
// unchanged and a positive one is applied.
func TestWithTimeout(t *testing.T) {
	client := NewClient("/tmp/x.sock")
	if client.WithTimeout(0) != client {
		t.Error("expected a non-positive timeout to return the same client")
	}
	if client.WithTimeout(-time.Second) != client {
		t.Error("expected a negative timeout to return the same client")
	}

	tuned := client.WithTimeout(2 * time.Second)
	if tuned == client {
		t.Fatal("expected a new client")
	}
	if tuned.timeout != 2*time.Second {
		t.Errorf("expected the timeout to be applied, got %v", tuned.timeout)
	}
	if tuned.socketPath != client.socketPath {
		t.Errorf("expected the socket path to be preserved, got %q", tuned.socketPath)
	}
}

// readResponse reads and decodes one response line.
func readResponse(t *testing.T, connection net.Conn) Response {
	t.Helper()

	if err := connection.SetReadDeadline(time.Now().Add(5 * time.Second)); err != nil {
		t.Fatalf("set deadline: %v", err)
	}
	buffer := make([]byte, 0, 4096)
	chunk := make([]byte, 1024)
	for {
		read, err := connection.Read(chunk)
		buffer = append(buffer, chunk[:read]...)
		if err != nil {
			t.Fatalf("read response: %v", err)
		}
		if read > 0 && buffer[len(buffer)-1] == '\n' {
			break
		}
	}

	var response Response
	if err := json.Unmarshal(buffer, &response); err != nil {
		t.Fatalf("decode response: %v", err)
	}
	return response
}
