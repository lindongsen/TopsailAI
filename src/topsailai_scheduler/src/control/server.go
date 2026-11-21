package control

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log/slog"
	"net"
	"os"
	"path/filepath"
	"sync"
	"time"

	"topsailai_scheduler/runtime"
)

// maxRequestBytes bounds one request line so a malformed client cannot make the
// daemon allocate without limit.
const maxRequestBytes = 64 * 1024

// Server serves the control contract on a Unix socket.
//
// It holds no scheduling state: every request is translated into a call on the
// injected runtime.Controller. That is what keeps the contract single-sourced
// while allowing several transports.
type Server struct {
	// controller is the daemon implementing the contract.
	controller runtime.Controller
	// socketPath is the Unix socket to listen on.
	socketPath string
	// logger records accepted requests and failures.
	logger *slog.Logger

	// mu guards listener so Close and Serve do not race.
	mu sync.Mutex
	// listener is the active socket listener, nil before Serve.
	listener net.Listener
}

// NewServer returns a server for the given controller and socket path.
func NewServer(controller runtime.Controller, socketPath string, logger *slog.Logger) *Server {
	return &Server{
		controller: controller,
		socketPath: socketPath,
		logger:     logger,
	}
}

// Serve listens and handles requests until ctx ends.
//
// A stale socket file left by a crashed daemon is removed before listening, so a
// restart is not blocked by a file nobody is serving.
func (s *Server) Serve(ctx context.Context) error {
	if err := os.MkdirAll(filepath.Dir(s.socketPath), 0o755); err != nil {
		return fmt.Errorf("create control socket directory: %w", err)
	}
	if err := removeStaleSocket(s.socketPath); err != nil {
		return err
	}

	listener, err := net.Listen("unix", s.socketPath)
	if err != nil {
		return fmt.Errorf("listen on control socket %q: %w", s.socketPath, err)
	}
	// The socket is a local control channel: only the owning user may use it.
	if err := os.Chmod(s.socketPath, 0o600); err != nil {
		_ = listener.Close()
		return fmt.Errorf("restrict control socket %q: %w", s.socketPath, err)
	}

	s.mu.Lock()
	s.listener = listener
	s.mu.Unlock()

	s.logger.Info("control socket listening", slog.String("socket", s.socketPath))

	// Closing the listener unblocks Accept when the context ends.
	stopped := make(chan struct{})
	go func() {
		select {
		case <-ctx.Done():
		case <-stopped:
		}
		_ = listener.Close()
	}()
	defer close(stopped)

	for {
		connection, acceptErr := listener.Accept()
		if acceptErr != nil {
			if ctx.Err() != nil {
				return nil
			}
			// A transient accept failure must not kill the control channel.
			s.logger.Warn("control accept failed", slog.String("error", acceptErr.Error()))
			continue
		}
		go s.handle(connection)
	}
}

// Close stops the listener and removes the socket file.
//
// The listener may already be closed by the shutdown path that unblocks Accept,
// so an already-closed listener is not an error: reporting it would make a
// normal shutdown look like a failure.
func (s *Server) Close() error {
	s.mu.Lock()
	listener := s.listener
	s.listener = nil
	s.mu.Unlock()

	var closeErr error
	if listener != nil {
		if err := listener.Close(); err != nil && !errors.Is(err, net.ErrClosed) {
			closeErr = err
		}
	}
	// The socket file is a runtime artifact, so it is removed on shutdown
	// instead of being left behind for the next start to clean up.
	if err := os.Remove(s.socketPath); err != nil && !os.IsNotExist(err) {
		s.logger.Warn("remove control socket failed", slog.String("error", err.Error()))
	}
	return closeErr
}

// handle serves one connection: read one request line, reply, close.
func (s *Server) handle(connection net.Conn) {
	defer func() {
		if err := connection.Close(); err != nil {
			s.logger.Debug("close control connection failed", slog.String("error", err.Error()))
		}
	}()

	// A client that connects and then stalls must not hold the handler forever.
	if err := connection.SetDeadline(time.Now().Add(30 * time.Second)); err != nil {
		s.logger.Debug("set control deadline failed", slog.String("error", err.Error()))
	}

	reader := bufio.NewReaderSize(connection, maxRequestBytes)
	line, err := reader.ReadBytes('\n')
	if err != nil && len(line) == 0 {
		s.logger.Debug("read control request failed", slog.String("error", err.Error()))
		return
	}

	response := s.dispatch(line)
	encoded, err := json.Marshal(response)
	if err != nil {
		s.logger.Error("encode control response failed", slog.String("error", err.Error()))
		return
	}
	encoded = append(encoded, '\n')
	if _, err := connection.Write(encoded); err != nil {
		s.logger.Debug("write control response failed", slog.String("error", err.Error()))
	}
}

// dispatch decodes one request and calls the contract.
func (s *Server) dispatch(line []byte) Response {
	request, err := DecodeRequest(line)
	if err != nil {
		s.logger.Warn("invalid control request", slog.String("error", err.Error()))
		return NewFailure(CodeInvalidRequest, err)
	}

	switch request.Op {
	case OpLaunch:
		result, err := s.controller.Launch(runtime.LaunchRequest{
			TaskID: request.TaskID,
			Wait:   request.Wait,
		})
		if err != nil {
			return s.failure(request, err)
		}
		return s.success(request, result)
	case OpStatus:
		snapshot, err := s.controller.Status()
		if err != nil {
			return s.failure(request, err)
		}
		return s.success(request, snapshot)
	case OpStop:
		result, err := s.controller.Stop(runtime.StopRequest{
			TaskID: request.TaskID,
			Force:  request.Force,
		})
		if err != nil {
			return s.failure(request, err)
		}
		return s.success(request, result)
	default:
		// DecodeRequest already rejected unknown ops, so this is unreachable.
		return NewFailure(CodeInvalidRequest, fmt.Errorf("unknown op %q", request.Op))
	}
}

// success encodes a result and logs the accepted request.
func (s *Server) success(request Request, data any) Response {
	response, err := NewSuccess(data)
	if err != nil {
		s.logger.Error("encode control result failed", slog.String("error", err.Error()))
		return NewFailure(CodeInternal, err)
	}
	s.logger.Info("control request served",
		slog.String("op", request.Op),
		slog.String("task", request.TaskID),
	)
	return response
}

// failure encodes an error with its stable code.
func (s *Server) failure(request Request, err error) Response {
	code := CodeForError(err)
	s.logger.Warn("control request failed",
		slog.String("op", request.Op),
		slog.String("task", request.TaskID),
		slog.String("code", code),
		slog.String("error", err.Error()),
	)
	return NewFailure(code, err)
}

// removeStaleSocket deletes a socket file that nobody is serving.
//
// A live socket is left alone: removing it would silently disconnect the running
// daemon from its CLI.
func removeStaleSocket(path string) error {
	info, err := os.Stat(path)
	if err != nil {
		if os.IsNotExist(err) {
			return nil
		}
		return fmt.Errorf("stat control socket %q: %w", path, err)
	}
	if info.Mode()&os.ModeSocket == 0 {
		return fmt.Errorf("control socket path %q exists and is not a socket", path)
	}

	connection, dialErr := net.DialTimeout("unix", path, time.Second)
	if dialErr == nil {
		_ = connection.Close()
		return fmt.Errorf("control socket %q is already in use by a running scheduler", path)
	}
	if !errors.Is(dialErr, os.ErrNotExist) {
		// The dial failed, so the file is a leftover from a dead process.
		if err := os.Remove(path); err != nil {
			return fmt.Errorf("remove stale control socket %q: %w", path, err)
		}
	}
	return nil
}
