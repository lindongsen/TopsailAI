// Package server provides the Server HTTP boundary.
package server

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strconv"
	"strings"
	"time"

	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// Handler serves authenticated Server APIs backed by durable storage.
// OutputRequester forwards bounded output snapshot requests to an Endpoint.
type OutputRequester interface {
	RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error)
}

// Handler serves authenticated Server APIs backed by durable storage.
type Handler struct {
	Store          *serverstorage.Store
	Authenticator  security.BearerAuthenticator
	CommandService *CommandService
	MaxBodyBytes   int64
	Broker         *EventBroker
	Output         OutputRequester
}

// NewHandler returns an HTTP handler with standard API routing.
func NewHandler(store *serverstorage.Store, token string) http.Handler {
	return NewHandlerWithBroker(store, token, nil)
}

// NewHandlerWithBroker returns an authenticated handler with latest-state events.
func NewHandlerWithBroker(store *serverstorage.Store, token string, broker *EventBroker) http.Handler {
	h := &Handler{Store: store, Authenticator: security.BearerAuthenticator{Token: token}, MaxBodyBytes: 4 << 20, Broker: broker}
	return h.authenticated(h.routes())
}

// ServeHTTP implements http.Handler.
func (h *Handler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	h.authenticated(h.routes()).ServeHTTP(w, r)
}

func (h *Handler) routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("/healthz", h.health)
	mux.HandleFunc("/readyz", h.ready)
	mux.HandleFunc("/api/v1/endpoints", h.endpoints)
	mux.HandleFunc("/api/v1/endpoints/", h.endpointResource)
	mux.HandleFunc("/api/v1/commands", h.commands)
	mux.HandleFunc("/api/v1/output", h.output)
	mux.HandleFunc("/api/v1/commands/", h.commandResource)
	if h.Broker != nil {
		mux.Handle("/api/v1/events", &EventHandler{Broker: h.Broker, Store: h.Store})
		mux.Handle("/api/v1/manifest", &EventHandler{Broker: h.Broker, Store: h.Store})
	}
	return mux
}

func (h *Handler) authenticated(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path == "/healthz" || r.URL.Path == "/readyz" {
			next.ServeHTTP(w, r)
			return
		}
		identity, ok := h.Authenticator.Authenticate(r)
		if !ok {
			h.writeError(w, http.StatusUnauthorized, "unauthorized", "authentication required")
			return
		}
		next.ServeHTTP(w, r.WithContext(security.WithAuthenticatedIdentity(r.Context(), identity)))
	})
}

func (h *Handler) health(w http.ResponseWriter, _ *http.Request) {
	h.write(w, http.StatusOK, 0, "ok", map[string]string{"status": "alive"})
}
func (h *Handler) ready(w http.ResponseWriter, _ *http.Request) {
	if h.Store == nil {
		h.writeError(w, http.StatusServiceUnavailable, "not_ready", "storage is unavailable")
		return
	}
	h.write(w, http.StatusOK, 0, "ok", map[string]string{"status": "ready"})
}

func (h *Handler) output(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		h.writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "method is not supported")
		return
	}
	if h.Output == nil {
		h.writeError(w, http.StatusServiceUnavailable, "endpoint_offline", "Endpoint output channel is unavailable")
		return
	}
	q := r.URL.Query()
	endpointID, resourceID := q.Get("endpoint_id"), q.Get("resource_id")
	if endpointID == "" || resourceID == "" {
		h.writeError(w, http.StatusBadRequest, "invalid_target", "endpoint_id and resource_id are required")
		return
	}
	maxBytes := parseInt(q.Get("max_bytes"), 64<<10)
	if maxBytes > 1<<20 {
		maxBytes = 1 << 20
	}
	response, err := h.Output.RequestOutput(r.Context(), endpointID, protocol.OutputSnapshotRequest{EndpointID: endpointID, ResourceID: resourceID, Generation: q.Get("generation"), MaxBytes: maxBytes})
	if err != nil {
		code := response.ErrorCode
		if code == "" {
			code = "endpoint_offline"
		}
		h.writeError(w, http.StatusServiceUnavailable, code, code)
		return
	}
	h.write(w, http.StatusOK, 0, "success", response)
}

func (h *Handler) endpoints(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet && r.Method != http.MethodPut {
		h.writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "method is not supported")
		return
	}
	if r.Method == http.MethodPut {
		h.putEndpoint(w, r)
		return
	}
	items, err := h.Store.ListEndpoints(r.Context(), queryOptions(r))
	if err != nil {
		h.writeError(w, http.StatusInternalServerError, "storage_error", err.Error())
		return
	}
	h.write(w, http.StatusOK, 0, "success", items)
}

func (h *Handler) endpointResource(w http.ResponseWriter, r *http.Request) {
	path := strings.TrimPrefix(r.URL.Path, "/api/v1/endpoints/")
	parts := strings.Split(strings.Trim(path, "/"), "/")
	if len(parts) != 2 || (parts[1] != "session-state" && parts[1] != "capabilities") {
		h.writeError(w, http.StatusNotFound, "not_found", "resource not found")
		return
	}
	if parts[1] == "capabilities" {
		if r.Method != http.MethodGet {
			h.writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "method is not supported")
			return
		}
		h.getCapabilities(w, r, parts[0])
		return
	}
	if r.Method == http.MethodPut {
		h.putInventory(w, r, parts[0])
		return
	}
	if r.Method == http.MethodGet {
		h.getInventory(w, r, parts[0])
		return
	}
	h.writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "method is not supported")
}

func (h *Handler) putEndpoint(w http.ResponseWriter, r *http.Request) {
	defer r.Body.Close()
	var endpoint protocol.Endpoint
	if err := decodeJSON(w, r, &endpoint, h.MaxBodyBytes); err != nil {
		h.writeError(w, http.StatusBadRequest, "invalid_request", err.Error())
		return
	}
	if err := h.Store.UpsertEndpoint(r.Context(), endpoint, time.Now().UnixMilli()); err != nil {
		h.writeError(w, http.StatusBadRequest, "invalid_endpoint", err.Error())
		return
	}
	h.write(w, http.StatusOK, 0, "success", endpoint)
}

func (h *Handler) putInventory(w http.ResponseWriter, r *http.Request, endpointID string) {
	defer r.Body.Close()
	var report protocol.InventoryReport
	if err := decodeJSON(w, r, &report, h.MaxBodyBytes); err != nil {
		h.writeError(w, http.StatusBadRequest, "invalid_request", err.Error())
		return
	}
	if err := h.Store.ReplaceInventory(r.Context(), endpointID, report, time.Now().UnixMilli()); err != nil {
		h.writeError(w, http.StatusBadRequest, "invalid_inventory", err.Error())
		return
	}
	if h.Broker != nil {
		h.Broker.Publish(endpointID, report.SnapshotRevision)
	}
	h.write(w, http.StatusOK, 0, "success", report)
}

// getCapabilities returns standard capabilities reported in the latest inventory.
func (h *Handler) getCapabilities(w http.ResponseWriter, r *http.Request, endpointID string) {
	report, err := h.Store.GetInventory(r.Context(), endpointID)
	if err != nil {
		h.writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	requested := r.URL.Query().Get("name")
	result := protocol.CapabilityDescriptor{Revision: "unknown"}
	for _, summary := range report.Adapters {
		if summary.Capabilities.Revision != "" {
			result.Revision = summary.Capabilities.Revision
		}
		result.Capabilities = append(result.Capabilities, summary.Capabilities.Capabilities...)
	}
	if requested != "" {
		for _, capability := range result.Capabilities {
			if capability.Name == requested {
				h.write(w, http.StatusOK, 0, "success", result)
				return
			}
		}
		h.writeError(w, http.StatusNotImplemented, "unsupported", "capability is unsupported")
		return
	}
	h.write(w, http.StatusOK, 0, "success", result)
}

func (h *Handler) getInventory(w http.ResponseWriter, r *http.Request, endpointID string) {
	report, err := h.Store.GetInventory(r.Context(), endpointID)
	if err != nil {
		h.writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	h.write(w, http.StatusOK, 0, "success", report)
}

func queryOptions(r *http.Request) serverstorage.QueryOptions {
	q := r.URL.Query()
	return serverstorage.QueryOptions{Offset: parseInt(q.Get("offset"), 0), Limit: parseInt(q.Get("limit"), 1000), SortKey: q.Get("sort_key"), OrderBy: q.Get("order_by")}
}
func parseInt(value string, fallback int) int {
	n, err := strconv.Atoi(value)
	if err != nil || n < 0 {
		return fallback
	}
	return n
}

func decodeJSON(w http.ResponseWriter, r *http.Request, target any, max int64) error {
	if max > 0 {
		r.Body = http.MaxBytesReader(w, r.Body, max)
	}
	decoder := json.NewDecoder(r.Body)
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(target); err != nil {
		return err
	}
	var extra any
	if err := decoder.Decode(&extra); err != io.EOF {
		if err == nil {
			return fmt.Errorf("request contains multiple JSON values")
		}
		return fmt.Errorf("trailing JSON: %w", err)
	}
	return nil
}

func (h *Handler) writeError(w http.ResponseWriter, status int, code, message string) {
	h.write(w, status, code, message, nil)
}
func (h *Handler) write(w http.ResponseWriter, status int, code any, message string, data any) {
	w.Header().Set("Content-Type", "application/json")
	w.Header().Set("X-Request-ID", security.NewRequestID())
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{"code": code, "message": message, "data": data, "request_id": w.Header().Get("X-Request-ID"), "timestamp": time.Now().UnixMilli()})
}

// NewHandlerWithCommands returns an authenticated HTTP handler with command services.
func NewHandlerWithCommands(store *serverstorage.Store, token string, commands *CommandService) http.Handler {
	return NewHandlerWithCommandsAndBroker(store, token, commands, nil)
}

// NewHandlerWithCommandsAndBroker returns an authenticated handler with commands and events.
func NewHandlerWithCommandsAndBroker(store *serverstorage.Store, token string, commands *CommandService, broker *EventBroker) http.Handler {
	return NewHandlerWithCommandsAndBrokerAndOutput(store, token, commands, broker, nil)
}

// NewHandlerWithCommandsAndBrokerAndOutput returns an authenticated handler with output forwarding.
func NewHandlerWithCommandsAndBrokerAndOutput(store *serverstorage.Store, token string, commands *CommandService, broker *EventBroker, output OutputRequester) http.Handler {
	h := &Handler{Store: store, Authenticator: security.BearerAuthenticator{Token: token}, CommandService: commands, MaxBodyBytes: 4 << 20, Broker: broker, Output: output}
	return h.authenticated(h.routes())
}
