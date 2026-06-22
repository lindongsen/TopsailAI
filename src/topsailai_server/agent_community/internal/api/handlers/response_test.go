package handlers

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/gin-gonic/gin"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestWriteDataResponseEnvelope(t *testing.T) {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)

	writeDataResponse(c, http.StatusOK, map[string]string{"id": "group-1"}, "trace-abc")

	require.Equal(t, http.StatusOK, w.Code)

	var body map[string]any
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))

	assert.Equal(t, "trace-abc", body["trace_id"])
	data, ok := body["data"].(map[string]any)
	require.True(t, ok, "data field should be an object")
	assert.Equal(t, "group-1", data["id"])
	assert.NotContains(t, body, "error")
}

func TestWriteListResponseEnvelope(t *testing.T) {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)

	items := []listItem{{"group-1"}, {"group-2"}}
	writeListResponse(c, http.StatusOK, items, 42, 5, 10, "trace-list")

	require.Equal(t, http.StatusOK, w.Code)

	var body map[string]any
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))

	assert.Equal(t, "trace-list", body["trace_id"])
	data, ok := body["data"].(map[string]any)
	require.True(t, ok, "data field should be an object")
	assert.Equal(t, float64(42), data["total"])
	assert.Equal(t, float64(5), data["offset"])
	assert.Equal(t, float64(10), data["limit"])
	assert.Len(t, data["items"], 2)
	assert.NotContains(t, data, "sort_key")
	assert.NotContains(t, data, "order_by")
	assert.NotContains(t, body, "error")
}

func TestWriteErrorResponseEnvelope(t *testing.T) {
	gin.SetMode(gin.TestMode)
	w := httptest.NewRecorder()
	c, _ := gin.CreateTestContext(w)

	writeErrorResponse(c, http.StatusBadRequest, "invalid request", "trace-err")

	require.Equal(t, http.StatusBadRequest, w.Code)

	var body map[string]any
	require.NoError(t, json.Unmarshal(w.Body.Bytes(), &body))

	assert.Equal(t, "trace-err", body["trace_id"])
	assert.Equal(t, "invalid request", body["error"])
	assert.NotContains(t, body, "data")
}

func TestErrorResponseStruct(t *testing.T) {
	r := errorResponse{
		Error:   "something went wrong",
		TraceID: "trace-x",
	}
	assert.Equal(t, "something went wrong", r.Error)
	assert.Equal(t, "trace-x", r.TraceID)
}

func TestDataResponseStruct(t *testing.T) {
	r := dataResponse{
		Data:    "payload",
		TraceID: "trace-y",
	}
	assert.Equal(t, "payload", r.Data)
	assert.Equal(t, "trace-y", r.TraceID)
	assert.Empty(t, r.Error)
}

func TestListResponseStruct(t *testing.T) {
	items := []listItem{{"a"}, {"b"}}
	r := listResponse{
		Data: listResponseData{
			Items:  items,
			Total:  2,
			Offset: 0,
			Limit:  10,
		},
		TraceID: "trace-z",
	}
	assert.Equal(t, items, r.Data.Items)
	assert.Equal(t, int64(2), r.Data.Total)
	assert.Equal(t, 0, r.Data.Offset)
	assert.Equal(t, 10, r.Data.Limit)
	assert.Equal(t, "trace-z", r.TraceID)
	assert.Empty(t, r.Error)
}

// listItem is a minimal serializable type used for list response tests.
type listItem struct {
	ID string `json:"id"`
}
