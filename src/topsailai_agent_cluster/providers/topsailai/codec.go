package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
)

const maxRequestBytes = 1 << 20

// decodeRequest decodes exactly one strict Provider CLI request.
func decodeRequest(document []byte) (request, error) {
	var value request
	decoder := json.NewDecoder(bytes.NewReader(document))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&value); err != nil {
		return request{}, fmt.Errorf("decode request: %w", err)
	}
	var extra any
	if err := decoder.Decode(&extra); !errors.Is(err, io.EOF) {
		if err == nil {
			return request{}, errors.New("decode request: extra JSON document")
		}
		return request{}, fmt.Errorf("decode request trailer: %w", err)
	}
	if err := validateRequest(value); err != nil {
		return request{}, err
	}
	return value, nil
}

// validateRequest checks the common frozen Provider CLI request envelope.
func validateRequest(value request) error {
	if value.Protocol != protocolName || value.Major != protocolMajor || value.Minor != protocolMinor {
		return errors.New("unsupported protocol version")
	}
	if value.RequestID == "" || value.AdapterID == "" || value.Function == "" {
		return errors.New("request_id, adapter_id and function are required")
	}
	if value.DeadlineAtMS < 1 {
		return errors.New("deadline_at_ms must be positive")
	}
	if value.Budget.MaxStdoutBytes < 1 || value.Budget.MaxStderrBytes < 1 || value.Budget.MaxRecords < 1 {
		return errors.New("provider budget values must be positive")
	}
	if len(value.Payload) == 0 || !json.Valid(value.Payload) || bytes.Equal(bytes.TrimSpace(value.Payload), []byte("null")) {
		return errors.New("payload must be non-null JSON")
	}
	return nil
}

// encodeResponse emits one compact response document.
func encodeResponse(writer io.Writer, value response) error {
	encoder := json.NewEncoder(writer)
	encoder.SetEscapeHTML(false)
	return encoder.Encode(value)
}
