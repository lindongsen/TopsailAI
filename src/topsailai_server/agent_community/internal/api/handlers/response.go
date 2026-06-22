// Package handlers provides HTTP handlers for the ACS API.
package handlers

import (
	"github.com/gin-gonic/gin"
)

// listResponseData is the standard data envelope returned by list endpoints.
type listResponseData struct {
	Items  interface{} `json:"items"`
	Total  int64       `json:"total"`
	Offset int         `json:"offset"`
	Limit  int         `json:"limit"`
}

// listResponse is the standard top-level response returned by list endpoints.
type listResponse struct {
	Data    listResponseData `json:"data"`
	Error   string           `json:"error"`
	TraceID string           `json:"trace_id"`
}

// writeListResponse writes a standard { data: { items, total, offset, limit }, error: "", trace_id } response.
func writeListResponse(c *gin.Context, status int, items interface{}, total int64, offset, limit int, traceID string) {
	c.JSON(status, listResponse{
		Data: listResponseData{
			Items:  items,
			Total:  total,
			Offset: offset,
			Limit:  limit,
		},
		Error:   "",
		TraceID: traceID,
	})
}

// dataResponse is the standard top-level response returned by single-object endpoints.
type dataResponse struct {
	Data    interface{} `json:"data"`
	Error   string      `json:"error"`
	TraceID string      `json:"trace_id"`
}

// writeDataResponse writes a standard { data: { ... }, error: "", trace_id } response.
func writeDataResponse(c *gin.Context, status int, data interface{}, traceID string) {
	c.JSON(status, dataResponse{
		Data:    data,
		Error:   "",
		TraceID: traceID,
	})
}
