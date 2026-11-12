package main

import (
	"fmt"
	"io"
	"os"
)

const exitProtocolFailure = 2

// main serves one Provider CLI request and exits.
func main() {
	if err := serve(os.Stdin, os.Stdout); err != nil {
		_, _ = fmt.Fprintf(os.Stderr, "agent-cluster-provider-topsailai: %v\n", err)
		os.Exit(exitProtocolFailure)
	}
}

// serve reads and handles exactly one unary request.
func serve(reader io.Reader, writer io.Writer) error {
	document, err := io.ReadAll(io.LimitReader(reader, maxRequestBytes+1))
	if err != nil {
		return fmt.Errorf("read request: %w", err)
	}
	if len(document) > maxRequestBytes {
		return fmt.Errorf("request exceeds %d bytes", maxRequestBytes)
	}
	request, err := decodeRequest(document)
	if err != nil {
		return err
	}
	return encodeResponse(writer, dispatch(request))
}

// dispatch handles only functions truthfully advertised by the descriptor.
func dispatch(request request) response {
	base := response{version: currentVersion(), RequestID: request.RequestID}
	if request.Function == functionDescribe {
		descriptor := topsailaiDescriptor()
		base.OK = true
		base.Descriptor = &descriptor
		return base
	}
	base.Error = &providerError{
		Code:            "unsupported",
		Message:         "provider function is not implemented",
		Retryable:       false,
		EffectCertainty: effectNotApplied,
	}
	return base
}
