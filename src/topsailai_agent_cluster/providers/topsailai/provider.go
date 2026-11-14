package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"time"
)

// commandRunner is the Provider-owned boundary to the installed TopsailAI CLI.
type commandRunner interface {
	Run(context.Context, []string, []byte) ([]byte, []byte, error)
}

// provider implements the standard Provider CLI functions with one local CLI runner.
type provider struct {
	runner commandRunner
	now    func() time.Time
	// control is the Provider-local ctl. action catalog loaded at startup. An
	// empty catalog advertises no action and refuses every ctl. operation.
	control controlCatalog
}

// newProvider builds one Provider from its immutable startup configuration.
//
// The catalog is a parameter rather than a process read, so the action surface is
// decided once at the boundary and every later decision uses the same value.
func newProvider(runner commandRunner, control controlCatalog) *provider {
	return &provider{runner: runner, now: time.Now, control: control}
}

// dispatch handles only functions truthfully advertised by the descriptor.
func (p *provider) dispatch(ctx context.Context, request request) response {
	base := response{version: currentVersion(), RequestID: request.RequestID}
	var err error
	switch request.Function {
	case functionDescribe:
		descriptor := topsailaiDescriptor(p.control)
		base.OK = true
		base.Descriptor = &descriptor
	case functionDiscover:
		base.Discovery, err = p.discover(ctx)
	case functionInspect:
		base.Inspection, err = p.inspect(ctx, request.Target)
	case functionExecute:
		base.Result, err = p.execute(ctx, request)
	case functionQuery:
		base.QueryResult, err = p.query(ctx, request.Query, request.Target, request.Payload)
	case functionReadOutput:
		base.Output, err = p.readOutput(ctx, request.Target, request.Payload)
	default:
		err = fmt.Errorf("%w: provider function is not implemented", errUnsupported)
	}
	if err == nil {
		base.OK = true
		return base
	}
	base.Error = &providerError{Code: errorCode(err), Message: err.Error(), Retryable: false, EffectCertainty: effectNotApplied}
	return base
}

func errorCode(err error) string {
	var coded interface{ ErrorCode() string }
	if errors.As(err, &coded) {
		return coded.ErrorCode()
	}
	if errors.Is(err, errUnsupported) {
		return "unsupported"
	}
	if errors.Is(err, errInvalidRequest) {
		return "invalid_request"
	}
	return "provider_error"
}

var (
	errUnsupported    = errors.New("unsupported")
	errInvalidRequest = errors.New("invalid request")
)

// codedError carries a provider error code that the Cluster has to act on.
//
// A plain error is reported as "provider_error", which tells the operator that
// the provider failed but not what happened. A session the provider does not know
// is a normal outcome of a read, not a fault, and the Cluster maps it to a
// different HTTP status, so the code has to survive the trip.
type codedError struct {
	code    string
	message string
}

// Error renders the provider message.
func (e codedError) Error() string { return e.message }

// ErrorCode reports the provider code so errorCode can classify the failure.
func (e codedError) ErrorCode() string { return e.code }

// providerSessionNotFoundCode is the provider's own code for a session it does
// not know. It is a provider protocol value, not a Cluster error code.
const providerSessionNotFoundCode = "session_not_found"

func decodeStrict(document []byte, value any) error {
	if bytes.Equal(bytes.TrimSpace(document), []byte("null")) {
		return errors.New("null JSON document")
	}
	decoder := json.NewDecoder(bytes.NewReader(document))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(value); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("extra JSON document")
		}
		return err
	}
	return nil
}

func runJSON(ctx context.Context, runner commandRunner, args []string, limit int, value any) error {
	stdout, stderr, err := runner.Run(ctx, args, nil)
	if len(stdout) > limit {
		return fmt.Errorf("provider response exceeds %d bytes", limit)
	}
	if err != nil {
		return fmt.Errorf("TopsailAI CLI failed: %w: %s", err, boundedText(stderr, 4096))
	}
	if err := decodeJSONDocument(stdout, value, false); err != nil {
		return fmt.Errorf("decode TopsailAI CLI response: %w", err)
	}
	return nil
}

// decodeJSONDocument accepts exactly one JSON document. Provider-business CLI
// responses may add fields, so strictFields is false there; public protocol
// payloads pass through decodeStrict and reject unknown fields.
func decodeJSONDocument(document []byte, value any, strictFields bool) error {
	decoder := json.NewDecoder(bytes.NewReader(document))
	if strictFields {
		decoder.DisallowUnknownFields()
	}
	if err := decoder.Decode(value); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return errors.New("extra JSON document")
		}
		return err
	}
	return nil
}

func boundedText(value []byte, limit int) string {
	if len(value) <= limit {
		return string(value)
	}
	return string(value[:limit])
}
