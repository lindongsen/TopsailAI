// Package filetool implements the file and folder capabilities exposed by the
// TopsailAI file tool as a reusable Go library.
//
// The package is deliberately free of CLI and storage-adapter dependencies so
// every capability can be unit tested in isolation. Callers pass explicit
// options; nothing is read from process-wide environment variables here.
package filetool

import (
	"errors"
	"fmt"
)

// ErrInvalidParameter reports a tool argument that cannot be interpreted.
var ErrInvalidParameter = errors.New("invalid parameter")

// ErrInvalidRange reports a line range that cannot be applied to a file.
var ErrInvalidRange = errors.New("invalid line range")

// ErrFileNotFound reports a file that does not exist when an operation
// requires an existing file.
var ErrFileNotFound = errors.New("file not found")

// ParameterError describes an invalid tool argument in a machine-readable way.
// It mirrors the invalid_request status used by the TopsailAI tool layer.
type ParameterError struct {
	// Parameter is the argument name that failed validation.
	Parameter string
	// Value is the rejected value.
	Value any
	// Reason explains why the value was rejected.
	Reason string
}

// Error renders the parameter error with its parameter name and reason.
func (e *ParameterError) Error() string {
	return fmt.Sprintf("%v: invalid %s=%v: %s", ErrInvalidParameter, e.Parameter, e.Value, e.Reason)
}

// Unwrap exposes ErrInvalidParameter so callers can test with errors.Is.
func (e *ParameterError) Unwrap() error { return ErrInvalidParameter }

// invalidParameter builds a ParameterError for a rejected argument.
func invalidParameter(parameter string, value any, reason string) error {
	return &ParameterError{Parameter: parameter, Value: value, Reason: reason}
}
