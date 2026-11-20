package main

import (
	"context"
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

// serve reads and handles exactly one Provider CLI request.
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
	// The control action catalog is immutable startup configuration: it is read once
	// here and passed down, so no later decision re-reads the process environment.
	control, err := loadControlCatalog(os.Environ())
	if err != nil {
		return err
	}
	// The platform capabilities are detected once here, beside the catalog, so no
	// later decision re-probes the host. The task directory and the project root are
	// resolved from the same environment for the same reason: one boundary read,
	// passed down.
	environment := os.Environ()
	provider := newProvider(newCLIRunner(environment), control, probePlatformCapabilities(), resolveTaskDir(environment), resolveProjectRoot(environment))
	if request.Function == functionFollowOutput {
		return provider.followOutput(context.Background(), request, writer)
	}
	return encodeResponse(writer, provider.dispatch(context.Background(), request))
}
