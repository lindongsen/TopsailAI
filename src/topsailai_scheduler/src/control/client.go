package control

import (
	"bufio"
	"encoding/json"
	"fmt"
	"net"
	"time"

	"topsailai_scheduler/runtime"
)

// dialTimeout bounds how long a client waits to reach the daemon.
const dialTimeout = 5 * time.Second

// requestTimeout bounds a whole request. A launch with Wait can legitimately
// take as long as the task's own timeout, so the caller passes its own value.
const requestTimeout = 30 * time.Second

// Client calls the control contract over the Unix socket.
//
// It is the CLI side of the same seam the server implements: the CLI never
// imports the daemon, so the two can be built and tested independently.
type Client struct {
	// socketPath is the Unix socket to connect to.
	socketPath string
	// timeout bounds one request.
	timeout time.Duration
}

// NewClient returns a client for the given socket path.
func NewClient(socketPath string) *Client {
	return &Client{socketPath: socketPath, timeout: requestTimeout}
}

// WithTimeout returns a copy of the client using a different request timeout.
//
// A waiting launch needs a longer bound than a status query, so the timeout is a
// parameter of the client rather than a process-wide setting.
func (c *Client) WithTimeout(timeout time.Duration) *Client {
	if timeout <= 0 {
		return c
	}
	return &Client{socketPath: c.socketPath, timeout: timeout}
}

// Launch asks the daemon to start one run of a task.
func (c *Client) Launch(request runtime.LaunchRequest) (runtime.LaunchResult, error) {
	var result runtime.LaunchResult
	if err := c.call(Request{Op: OpLaunch, TaskID: request.TaskID, Wait: request.Wait}, &result); err != nil {
		return runtime.LaunchResult{}, err
	}
	return result, nil
}

// Status asks the daemon for the current state of every task.
func (c *Client) Status() (runtime.Snapshot, error) {
	var snapshot runtime.Snapshot
	if err := c.call(Request{Op: OpStatus}, &snapshot); err != nil {
		return runtime.Snapshot{}, err
	}
	return snapshot, nil
}

// Stop asks the daemon to stop a running task.
func (c *Client) Stop(request runtime.StopRequest) (runtime.StopResult, error) {
	var result runtime.StopResult
	if err := c.call(Request{Op: OpStop, TaskID: request.TaskID, Force: request.Force}, &result); err != nil {
		return runtime.StopResult{}, err
	}
	return result, nil
}

// call sends one request and decodes the reply into out.
func (c *Client) call(request Request, out any) error {
	encoded, err := json.Marshal(request)
	if err != nil {
		return fmt.Errorf("encode request: %w", err)
	}
	encoded = append(encoded, '\n')

	connection, err := net.DialTimeout("unix", c.socketPath, dialTimeout)
	if err != nil {
		return fmt.Errorf("connect to scheduler at %q: %w", c.socketPath, err)
	}
	defer func() { _ = connection.Close() }()

	if err := connection.SetDeadline(time.Now().Add(c.timeout)); err != nil {
		return fmt.Errorf("set request deadline: %w", err)
	}
	if _, err := connection.Write(encoded); err != nil {
		return fmt.Errorf("send request: %w", err)
	}

	line, err := bufio.NewReader(connection).ReadBytes('\n')
	if err != nil && len(line) == 0 {
		return fmt.Errorf("read response: %w", err)
	}

	var response Response
	if err := json.Unmarshal(line, &response); err != nil {
		return fmt.Errorf("decode response: %w", err)
	}
	if !response.OK {
		return &RemoteError{Code: response.Code, Message: response.Error}
	}
	if out == nil || len(response.Data) == 0 {
		return nil
	}
	if err := json.Unmarshal(response.Data, out); err != nil {
		return fmt.Errorf("decode response data: %w", err)
	}
	return nil
}

// RemoteError is an error reported by the daemon.
//
// It keeps the wire code so a caller can branch on the condition without
// matching message text.
type RemoteError struct {
	// Code is the stable wire code.
	Code string
	// Message is the daemon's error message.
	Message string
}

// Error implements the error interface.
func (e *RemoteError) Error() string {
	if e.Message == "" {
		return fmt.Sprintf("scheduler error: %s", e.Code)
	}
	return fmt.Sprintf("%s: %s", e.Code, e.Message)
}
