package handlers

import (
	"encoding/json"
	"testing"

	"github.com/stretchr/testify/require"
)

// dataResponseWrapper mirrors the production dataResponse shape for tests.
type dataResponseWrapper struct {
	Data    json.RawMessage `json:"data"`
	Error   string          `json:"error"`
	TraceID string          `json:"trace_id"`
}

// unmarshalDataResponse parses the standard {data, error, trace_id} envelope and
// unmarshals the data payload into v.
func unmarshalDataResponse(t *testing.T, body []byte, v interface{}) {
	t.Helper()
	var wrapper dataResponseWrapper
	require.NoError(t, json.Unmarshal(body, &wrapper))
	require.NoError(t, json.Unmarshal(wrapper.Data, v))
}
