package helpdispatch

import (
	"errors"
	"fmt"
)

// UsageError marks a command line the program rejected before doing anything.
//
// It exists because the exit status and the message must agree. The help text of both
// binaries states that a message beginning "usage:" always accompanies status 2, so a
// script can tell a rejected command line from a failed operation without parsing the
// text. A message that says "usage:" while the status says 1 leaves that script unable
// to branch, which is the defect the CLI already recorded and fixed.
//
// The prefix is added here rather than at each call site, so a caller cannot produce a
// usage error whose message does not begin with "usage:".
type UsageError struct {
	// Message is the reason, without the "usage:" prefix.
	Message string
}

// Error returns the message with the prefix the exit status promises.
func (e *UsageError) Error() string {
	return "usage: " + e.Message
}

// Usagef builds a UsageError from a format and its arguments.
func Usagef(format string, arguments ...any) error {
	return &UsageError{Message: fmt.Sprintf(format, arguments...)}
}

// IsUsage reports whether an error is a rejected command line.
//
// It is used to choose the exit status, so it must answer for a wrapped error too: a
// caller that adds context to a usage error must not thereby turn status 2 into 1.
func IsUsage(err error) bool {
	var usage *UsageError
	return errors.As(err, &usage)
}

// PrintedError reports a refusal whose message has already been written.
//
// A `help` naming something the binary does not offer is answered with a complete
// message and status 2. Returning that message as an ordinary error would print it a
// second time, because the caller prints every error it receives. This type carries the
// status and nothing else, so the caller can exit with it without writing anything.
type PrintedError struct {
	// Status is the exit status the refusal already announced.
	Status int
}

// Error returns an empty message, because the message was written by whoever built it.
func (e *PrintedError) Error() string {
	return ""
}
