package commandexec

import (
	"context"
	"errors"
	"fmt"
	"io"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"
)

// MaxStreamBytes bounds one captured stream of an allowlisted command.
//
// The receipt bound is applied afterwards, so this limit only prevents an
// unbounded read from exhausting Endpoint memory.
const MaxStreamBytes = 256 << 10

// waitDelay bounds how long Wait blocks after cancellation, so a grandchild that
// inherited the pipes cannot keep the Endpoint waiting forever.
const waitDelay = 5 * time.Second

// ExecRunner runs a local command without a shell.
type ExecRunner struct {
	Timeout time.Duration
}

// Run executes argv in dir and captures bounded stdout and stderr.
//
// A non-zero exit is a legitimate command result, not a runner failure: a command
// such as "git status" reports "changes present" through its exit code. Only a
// start failure or an exceeded lifetime is returned as an error.
func (r ExecRunner) Run(parent context.Context, executable string, argv []string, dir string) (Outcome, error) {
	timeout := r.Timeout
	if timeout <= 0 {
		timeout = DefaultTimeout
	}
	if len(argv) == 0 {
		return Outcome{}, errors.New("argv is required")
	}
	ctx, cancel := context.WithTimeout(parent, timeout)
	defer cancel()
	// argv[0] is the program name the allowlist matched, and exec.CommandContext
	// already passes executable as the child's argv[0]. Forwarding argv[0] again
	// would shift every argument by one: "echo hello" would print "echo hello"
	// and "sleep 30" would receive "sleep" as its duration and exit at once.
	command := exec.CommandContext(ctx, executable, argv[1:]...)
	command.Dir = dir
	command.Env = Environment()
	// The default cancellation kills only the direct child, which leaves any
	// process it spawned running after the Endpoint reported the command done.
	configureProcessGroup(command)
	command.Cancel = func() error { return killProcessGroup(command) }
	command.WaitDelay = waitDelay
	stdout, err := command.StdoutPipe()
	if err != nil {
		return Outcome{}, fmt.Errorf("prepare command stdout: %w", err)
	}
	stderr, err := command.StderrPipe()
	if err != nil {
		return Outcome{}, fmt.Errorf("prepare command stderr: %w", err)
	}
	if err := command.Start(); err != nil {
		return Outcome{}, fmt.Errorf("start command %q: %w", argv[0], err)
	}
	// Both pipes must be drained concurrently: a command that fills the stderr
	// pipe while the caller is still reading stdout would block forever.
	var wait sync.WaitGroup
	var outBuf, errBuf []byte
	var outTruncated, errTruncated bool
	wait.Add(2)
	go func() {
		defer wait.Done()
		outBuf, outTruncated = readBounded(stdout)
	}()
	go func() {
		defer wait.Done()
		errBuf, errTruncated = readBounded(stderr)
	}()
	wait.Wait()
	waitErr := command.Wait()
	outcome := Outcome{Stdout: outBuf, Stderr: errBuf, Truncated: outTruncated || errTruncated}
	if ctx.Err() != nil {
		return outcome, ErrTimeout
	}
	if waitErr != nil {
		var exitErr *exec.ExitError
		if errors.As(waitErr, &exitErr) {
			outcome.ExitCode = exitErr.ExitCode()
			return outcome, nil
		}
		return outcome, fmt.Errorf("wait for command %q: %w", argv[0], waitErr)
	}
	return outcome, nil
}

// readBounded reads at most MaxStreamBytes and reports truncation.
func readBounded(reader io.Reader) ([]byte, bool) {
	data, err := io.ReadAll(io.LimitReader(reader, MaxStreamBytes+1))
	if err != nil {
		return data, false
	}
	if len(data) > MaxStreamBytes {
		return data[:MaxStreamBytes], true
	}
	return data, false
}

// Environment returns a minimal environment for an operator command.
//
// The Endpoint process environment carries provider credentials, database
// connection strings and tokens. Passing it through would hand every allowlisted
// command the Endpoint's own secrets, so only the variables a command needs to
// resolve its program and locate its configuration are forwarded.
func Environment() []string {
	inherited := make(map[string]string, len(os.Environ()))
	for _, entry := range os.Environ() {
		if index := strings.IndexByte(entry, '='); index > 0 {
			inherited[entry[:index]] = entry[index+1:]
		}
	}
	environment := make([]string, 0, 8)
	for _, name := range []string{"PATH", "HOME", "LANG", "LC_ALL", "TZ", "TMPDIR"} {
		if value, ok := inherited[name]; ok {
			environment = append(environment, name+"="+value)
		}
	}
	// A dumb terminal keeps programs from emitting escape sequences that the
	// caller would have to strip before rendering.
	return append(environment, "TERM=dumb")
}
