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
	return encodeResponse(writer, newProvider(newCLIRunner(os.Environ())).dispatch(context.Background(), request))
}
