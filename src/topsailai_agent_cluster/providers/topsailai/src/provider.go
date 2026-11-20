package main

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"strings"
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
	// platform is the host support detected at startup. A host that cannot stop a
	// provider process neither advertises nor serves agent.stop.
	platform platformCapabilities
	// taskDir is the provider stdout directory resolved once at startup. It lets a
	// row-scoped output read prove its target from filenames instead of paying for
	// a full workspace discovery before the first byte. An empty value disables
	// that shortcut, so every read falls back to discovery.
	taskDir string
	// projectRoot is the Endpoint-local project root resolved once at startup. It
	// confines project.add and project.remove to folders this Endpoint approved. An
	// empty value disables both operations, because a default root would grant a
	// remote caller the right to register folders nobody approved.
	projectRoot string
}

// newProvider builds one Provider from its immutable startup configuration.
//
// The catalog, the platform capabilities, the task directory and the project root
// are parameters rather than process reads, so the action surface, the operation
// surface, the output location and the registration boundary are decided once at
// the boundary and every later decision uses the same values.
func newProvider(runner commandRunner, control controlCatalog, platform platformCapabilities, taskDir string, projectRoot string) *provider {
	return &provider{runner: runner, now: time.Now, control: control, platform: platform, taskDir: taskDir, projectRoot: projectRoot}
}

// dispatch handles only functions truthfully advertised by the descriptor.
func (p *provider) dispatch(ctx context.Context, request request) response {
	base := response{version: currentVersion(), RequestID: request.RequestID}
	var err error
	switch request.Function {
	case functionDescribe:
		descriptor := topsailaiDescriptor(p.control, p.platform)
		base.OK = true
		base.Descriptor = &descriptor
	case functionDiscover:
		base.Discovery, err = p.discover(ctx)
	case functionInspect:
		base.Inspection, err = p.inspect(ctx, request.Target)
	case functionResolve:
		base.Resolution, err = p.resolveSessionHandle(request.Payload)
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
	// The three project registration errors are coded rather than plain, because
	// the Cluster maps each one to a different remedy: an unconfigured root is a
	// deployment gap, an escaped path is a request the operator must correct, and a
	// non-directory is a path that does not resolve.
	errProjectRootUnconfigured = codedError{code: "project_root_unconfigured", message: "project root is not configured"}
	errProjectPathOutsideRoot  = codedError{code: "project_path_outside_root", message: "project path is outside the configured project root"}
	errProjectPathNotDirectory = codedError{code: "project_path_not_directory", message: "project path is not an existing directory"}
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

// runJSON runs one provider CLI invocation and decodes its single JSON document.
//
// A non-zero exit is reported with the provider's own reason when the CLI wrote one.
// The provider states a failure inside its JSON document rather than on stderr: a
// rejected control call carries `response.error`, and a business read carries
// `error_code` with `message`, while stderr stays empty. Formatting only stderr
// therefore produced `exit status 6: ` with no cause, and the operator read a 502 that
// named neither the call nor the reason. The document is inspected before the exit
// status for the same reason providerDocumentFailure does it: the reason is in the
// document, not in the status.
//
// The classification is deliberately unchanged. This only enriches the message, so a
// caller that maps a plain error to provider_error keeps doing so, and a failure never
// becomes a success.
func runJSON(ctx context.Context, runner commandRunner, args []string, limit int, value any) error {
	stdout, stderr, err := runner.Run(ctx, args, nil)
	if len(stdout) > limit {
		return fmt.Errorf("provider response exceeds %d bytes", limit)
	}
	if err != nil {
		return fmt.Errorf("TopsailAI CLI failed: %w: %s", err, providerFailureDetail(stdout, stderr))
	}
	if err := decodeJSONDocument(stdout, value, false); err != nil {
		return fmt.Errorf("decode TopsailAI CLI response: %w", err)
	}
	return nil
}

// providerFailureDetail reports why a failed provider invocation failed.
//
// The provider states the reason inside its JSON document, so the document is read
// first and stderr is only the fallback. Both are bounded, because a provider that
// writes a large document must not turn one log line into megabytes.
func providerFailureDetail(stdout, stderr []byte) string {
	if reason := providerDocumentReason(stdout); reason != "" {
		return reason
	}
	return boundedText(stderr, 4096)
}

// providerDocumentReason extracts the provider's own failure text from a document.
//
// Two shapes carry it, and both are read because this helper serves control calls and
// business reads alike: a control envelope reports `response.error`, while a business
// read reports `error_code` with `message`. An empty result means the document carried
// no reason, which is not an error; the caller then falls back to stderr.
func providerDocumentReason(stdout []byte) string {
	if len(bytes.TrimSpace(stdout)) == 0 {
		return ""
	}
	var probe struct {
		ErrorCode string `json:"error_code"`
		Message   string `json:"message"`
		Response  *struct {
			Error string `json:"error"`
		} `json:"response"`
	}
	if err := decodeJSONDocument(stdout, &probe, false); err != nil {
		return ""
	}
	if probe.Response != nil {
		if reason := strings.TrimSpace(probe.Response.Error); reason != "" {
			return boundedText([]byte(reason), 4096)
		}
	}
	code := strings.TrimSpace(probe.ErrorCode)
	message := strings.TrimSpace(probe.Message)
	switch {
	case code != "" && message != "":
		return boundedText([]byte(code+": "+message), 4096)
	case message != "":
		return boundedText([]byte(message), 4096)
	case code != "":
		return boundedText([]byte(code), 4096)
	}
	return ""
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
