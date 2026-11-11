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

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// endpointTokenHeader carries the caller's Endpoint token on a read request.
//
// A read is an HTTP GET, so it has no request body to carry the token. The token
// travels in a header rather than a query parameter because a URL is recorded by
// Server access logs, reverse proxies and shell history, while a header is not
// recorded by default.
const endpointTokenHeader = "X-Endpoint-Token"

// requireRegisteredEndpoint refuses an unknown endpoint identifier before the
// transport is consulted, and writes the rejection itself.
//
// Reachability has two distinct failures and they must not share one answer. An
// identifier that was never registered is a caller mistake, so it is reported as
// not found. A registered identifier with no live connection is an outage, so it
// is reported as unavailable. Collapsing both into one code would tell an
// operator to investigate a machine that does not exist, and would hide a typo
// behind an outage report.
//
// This is a reachability check, not an authorization check: it decides whether
// the Server can route the request at all, never whether the caller may make it.
func (h *Handler) requireRegisteredEndpoint(w http.ResponseWriter, r *http.Request, endpointID string) bool {
	if h.Store == nil {
		return true
	}
	_, known, err := h.Store.GetEndpoint(r.Context(), endpointID)
	if err != nil {
		h.writeError(w, http.StatusInternalServerError, "storage_error", err.Error())
		return false
	}
	if !known {
		h.writeError(w, http.StatusNotFound, "endpoint_not_found", "endpoint "+endpointID+" is not registered")
		return false
	}
	return true
}

// Handler serves authenticated Server APIs backed by durable storage.
// OutputRequester forwards bounded output snapshot requests to an Endpoint.
type OutputRequester interface {
	RequestOutput(context.Context, string, protocol.OutputSnapshotRequest) (protocol.OutputSnapshotResponse, error)
}

// OutputFollower starts one streaming output follow and returns its event stream.
// It is a separate interface from OutputRequester because a snapshot has exactly
// one response while a follow has many, so a transport that cannot stream must
// not be forced to pretend it can.
type OutputFollower interface {
	RequestFollow(context.Context, string, protocol.OutputFollowRequest) (<-chan channel.FollowEvent, error)
}

// RefreshRequester forces one fresh Endpoint collection and returns its committed report.
type RefreshRequester interface {
	RequestRefreshAndWait(context.Context, string) (protocol.InventoryReport, error)
}

// Handler serves authenticated Server APIs backed by durable storage.
type Handler struct {
	Store          *serverstorage.Store
	Authenticator  security.BearerAuthenticator
	CommandService *CommandService
	MaxBodyBytes   int64
	Broker         *EventBroker
	Output         OutputRequester
	Refresh        RefreshRequester
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
	mux.HandleFunc("/api/v1/output/follow", h.outputFollow)
	mux.HandleFunc("/api/v1/launch-options", h.launchOptions)
	mux.HandleFunc("/api/v1/history", h.history)
	mux.HandleFunc("/api/v1/messages", h.messages)
	mux.HandleFunc("/api/v1/model-catalog", h.modelCatalog)
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
		identity, scopes, ok := h.Authenticator.AuthenticateScopes(r)
		if !ok {
			h.writeError(w, http.StatusUnauthorized, "unauthorized", "authentication required")
			return
		}
		ctx := security.WithAuthenticatedIdentity(r.Context(), identity)
		ctx = security.WithAuthenticatedScopes(ctx, scopes)
		// The Endpoint token is carried, never validated here. Authorization
		// belongs to the Endpoint that owns the machine, so the Server only
		// forwards this credential and never decides what it permits.
		ctx = security.WithEndpointToken(ctx, r.Header.Get(endpointTokenHeader))
		next.ServeHTTP(w, r.WithContext(ctx))
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
	if !h.requireRegisteredEndpoint(w, r, endpointID) {
		return
	}
	maxBytes := parseInt(q.Get("max_bytes"), 64<<10)
	if maxBytes > 1<<20 {
		maxBytes = 1 << 20
	}
	response, err := h.Output.RequestOutput(r.Context(), endpointID, protocol.OutputSnapshotRequest{EndpointID: endpointID, ResourceID: resourceID, ProviderGeneration: q.Get("provider_generation"), MaxBytes: maxBytes, MaxLines: parseMaxLines(q.Get("max_lines"))})
	if err != nil {
		code := response.ErrorCode
		if code == "" {
			code = "endpoint_offline"
		}
		h.writeError(w, http.StatusServiceUnavailable, code, code)
		return
	}
	// A refusal arrives as an error code with no Go error, because the Endpoint
	// answered the request rather than failing it. Reporting it as a successful
	// snapshot would hand the operator an empty panel and no reason, so the code
	// is classified before the success path.
	if response.ErrorCode == protocol.PolicyDenied {
		h.writeError(w, http.StatusForbidden, protocol.PolicyDenied, "operation output.read is not permitted for this endpoint token")
		return
	}
	h.write(w, http.StatusOK, 0, "success", response)
}

// outputFollow streams followed output records as newline-delimited JSON.
//
// The response is a stream rather than one envelope because a follow has no
// natural end: the operator watches until they stop. Each line is one chunk, and
// exactly one terminal line carries the end record, so a client that stops
// reading without an end record must treat the stream as interrupted rather than
// complete. Chunk lines are flushed immediately; buffering them would defeat the
// purpose of following.
func (h *Handler) outputFollow(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		h.writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "method is not supported")
		return
	}
	follower, ok := h.Output.(OutputFollower)
	if !ok {
		// A transport without streaming support reports unsupported instead of
		// degrading into a snapshot, because a snapshot presented as a follow
		// would never update.
		h.writeError(w, http.StatusServiceUnavailable, "unsupported", "Endpoint output follow is unavailable")
		return
	}
	q := r.URL.Query()
	endpointID, resourceID := q.Get("endpoint_id"), q.Get("resource_id")
	if endpointID == "" || resourceID == "" {
		h.writeError(w, http.StatusBadRequest, "invalid_target", "endpoint_id and resource_id are required")
		return
	}
	if !h.requireRegisteredEndpoint(w, r, endpointID) {
		return
	}
	maxBytes := parseInt(q.Get("max_bytes"), 64<<10)
	if maxBytes > 1<<20 {
		maxBytes = 1 << 20
	}
	events, err := follower.RequestFollow(r.Context(), endpointID, protocol.OutputFollowRequest{EndpointID: endpointID, ResourceID: resourceID, ProviderGeneration: q.Get("provider_generation"), MaxBytes: maxBytes, MaxLines: parseMaxLines(q.Get("max_lines"))})
	if err != nil {
		h.writeError(w, http.StatusServiceUnavailable, "endpoint_offline", err.Error())
		return
	}
	flusher, _ := w.(http.Flusher)
	w.Header().Set("Content-Type", "application/x-ndjson")
	w.Header().Set("Cache-Control", "no-store")
	w.Header().Set("X-Request-ID", security.NewRequestID())
	w.WriteHeader(http.StatusOK)
	encoder := json.NewEncoder(w)
	for event := range events {
		record := map[string]any{"type": "chunk"}
		if event.End != nil {
			record = map[string]any{"type": "end", "error_code": event.End.ErrorCode, "observed_at_ms": event.End.ObservedAtMS, "truncated": event.End.Truncated}
		} else if event.Chunk != nil {
			record["lines"] = event.Chunk.Lines
			record["observed_at_ms"] = event.Chunk.ObservedAtMS
			record["truncated"] = event.Chunk.Truncated
		}
		if err := encoder.Encode(record); err != nil {
			// The client stopped reading. Returning releases the follow through
			// the request context, so the provider child is not left streaming.
			return
		}
		if flusher != nil {
			flusher.Flush()
		}
		if event.End != nil {
			return
		}
	}
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
	if len(parts) == 3 && parts[1] == "session-state" && parts[2] == "refresh" {
		if r.Method != http.MethodPost {
			h.writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "method is not supported")
			return
		}
		h.refreshInventory(w, r, parts[0])
		return
	}
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

// refreshTimeout bounds one forced collection so a slow Endpoint cannot hold the request open.
// It exceeds the Endpoint collection budget so the Endpoint reports its own failure first.
const refreshTimeout = 30 * time.Second

// refreshInventory forces one fresh Endpoint collection and returns the committed document.
// The response is re-read from storage, so it always equals a following GET session-state.
func (h *Handler) refreshInventory(w http.ResponseWriter, r *http.Request, endpointID string) {
	if h.Refresh == nil {
		h.writeError(w, http.StatusServiceUnavailable, "unavailable", "forced collection channel is unavailable")
		return
	}
	ctx, cancel := context.WithTimeout(r.Context(), refreshTimeout)
	defer cancel()
	submitted, err := h.Refresh.RequestRefreshAndWait(ctx, endpointID)
	if err != nil {
		h.writeError(w, http.StatusServiceUnavailable, "endpoint_unavailable", "forced collection failed: "+err.Error())
		return
	}
	committed, err := h.Store.GetInventory(ctx, endpointID)
	if err != nil {
		h.writeError(w, http.StatusServiceUnavailable, "not_committed", "forced collection was not committed: "+err.Error())
		return
	}
	// Storage silently ignores a report that is not newer than the stored document, so a
	// submitted report alone cannot prove freshness; the committed document must be at
	// least as new as the report this request forced.
	if committed.ObservedAtMS < submitted.ObservedAtMS || (committed.ObservedAtMS == submitted.ObservedAtMS && committed.SnapshotRevision < submitted.SnapshotRevision) {
		h.writeError(w, http.StatusConflict, "not_committed", "forced collection was not committed")
		return
	}
	h.write(w, http.StatusOK, 0, "success", committed)
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

// parseMaxLines bounds an optional provider line count. An absent or invalid
// value keeps the provider default, and an explicit count is clamped to the
// documented provider range so a caller cannot request unbounded output.
func parseMaxLines(value string) int {
	n, err := strconv.Atoi(value)
	if err != nil || n <= 0 {
		return 0
	}
	if n > 10000 {
		return 10000
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
	return NewHandlerWithCommandsAndBrokerAndOutputAndRefresh(store, token, commands, broker, output, nil)
}

// NewHandlerWithCommandsAndBrokerAndOutputAndRefresh returns an authenticated handler
// with output forwarding and forced Endpoint collection.
func NewHandlerWithCommandsAndBrokerAndOutputAndRefresh(store *serverstorage.Store, token string, commands *CommandService, broker *EventBroker, output OutputRequester, refresh RefreshRequester) http.Handler {
	return NewHandlerWithScopes(store, token, nil, commands, broker, output, refresh)
}

// NewHandlerWithScopes returns an authenticated handler that restricts the bearer
// token to the supplied operator scopes. An empty scope list leaves the credential
// unrestricted, which is the single-administrator deployment.
func NewHandlerWithScopes(store *serverstorage.Store, token string, scopes []string, commands *CommandService, broker *EventBroker, output OutputRequester, refresh RefreshRequester) http.Handler {
	h := &Handler{Store: store, Authenticator: security.BearerAuthenticator{Token: token, Scopes: security.NewScopeSet(scopes...)}, CommandService: commands, MaxBodyBytes: 4 << 20, Broker: broker, Output: output, Refresh: refresh}
	return h.authenticated(h.routes())
}
