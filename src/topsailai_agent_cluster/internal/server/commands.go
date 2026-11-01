package server

import (
	"context"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"topsailai_agent_cluster/internal/channel"
	"topsailai_agent_cluster/internal/protocol"
	"topsailai_agent_cluster/internal/security"
	serverstorage "topsailai_agent_cluster/internal/storage/server"
)

// Transport sends an admitted immutable intent to an Endpoint.
type Transport interface {
	Send(context.Context, protocol.TransportEnvelope) error
}

// CommandService owns Server-side command admission and dispatch.
type CommandService struct {
	Store         *serverstorage.Store
	Transport     Transport
	Now           func() time.Time
	DispatchDelay time.Duration
	HoldPhase     string
	HoldDir       string
	Hold          func(string, string, string) error
}

// ChannelTransport dispatches immutable intents through the current channel peer.
type ChannelTransport struct {
	Channel *channel.Server
}

// Send delivers one transport envelope to its endpoint-bound channel.
func (t ChannelTransport) Send(ctx context.Context, envelope protocol.TransportEnvelope) error {
	if t.Channel == nil {
		return errors.New("channel server is unavailable")
	}
	return t.Channel.SendCommand(ctx, envelope.EndpointInstanceID, channel.Frame{
		Type:            channel.FrameCommand,
		ProtocolVersion: channel.ProtocolVersion,
		FrameID:         envelope.FrameID,
		RequestID:       envelope.RequestID,
		Intent:          &envelope.Intent,
	})
}

// Admit validates and durably records an immutable intent before dispatch.
func (s *CommandService) Admit(ctx context.Context, intent protocol.ImmutableIntent, requestHash string) (serverstorage.CommandRecord, bool, error) {
	if s.Store == nil || intent.CommandID == "" {
		return serverstorage.CommandRecord{}, false, errors.New("store and command ID are required")
	}
	existing, lookupErr := s.Store.GetCommand(ctx, intent.CommandID)
	if lookupErr == nil {
		if existing.RequestHash != requestHash {
			return serverstorage.CommandRecord{}, false, errors.New("command ID conflicts with a different intent")
		}
		return existing, false, nil
	}
	if err := s.Store.AdmitCommand(ctx, intent, requestHash, s.now().UnixMilli()); err != nil {
		return serverstorage.CommandRecord{}, false, err
	}
	record, err := s.Store.GetCommand(ctx, intent.CommandID)
	if err != nil {
		return record, false, err
	}
	return record, true, nil
}

// Dispatch claims an admitted command and sends its transport envelope exactly once.
func (s *CommandService) Dispatch(ctx context.Context, intent protocol.ImmutableIntent, requestHash, requestID string) error {
	if s.DispatchDelay > 0 {
		timer := time.NewTimer(s.DispatchDelay)
		select {
		case <-ctx.Done():
			timer.Stop()
			return ctx.Err()
		case <-timer.C:
		}
	}
	claimed, err := s.Store.DispatchCommand(ctx, intent.CommandID, s.now().UnixMilli())
	if err != nil {
		return err
	}
	if !claimed {
		return errors.New("command is no longer dispatchable")
	}
	if s.Hold != nil && s.HoldPhase == "dispatched" {
		if err := s.Hold(intent.CommandID, s.HoldPhase, s.HoldDir); err != nil {
			return err
		}
	}
	if s.Transport == nil {
		return errors.New("endpoint transport is unavailable")
	}
	err = s.Transport.Send(ctx, protocol.TransportEnvelope{ProtocolVersion: "v1", FrameID: intent.CommandID, ConnectionGeneration: "", EndpointInstanceID: intent.EndpointID, RequestID: requestID, Intent: intent})
	return err
}

func (s *CommandService) now() time.Time {
	if s.Now != nil {
		return s.Now()
	}
	return time.Now()
}

func (h *Handler) commands(w http.ResponseWriter, r *http.Request) {
	if h.CommandService == nil {
		h.writeError(w, http.StatusServiceUnavailable, "unavailable", "command service is unavailable")
		return
	}
	if r.Method == http.MethodPost {
		h.admitCommand(w, r)
		return
	}
	if r.Method == http.MethodGet {
		limit := parseCommandLimit(r.URL.Query().Get("limit"))
		records, err := h.CommandService.Store.ListCommands(r.Context(), r.URL.Query().Get("endpoint_id"), r.URL.Query().Get("resource_id"), limit)
		if err != nil {
			h.writeError(w, http.StatusInternalServerError, "storage_error", err.Error())
			return
		}
		h.write(w, http.StatusOK, 0, "success", records)
		return
	}
	h.writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "method is not supported")
}
func (h *Handler) commandResource(w http.ResponseWriter, r *http.Request) {
	if h.CommandService == nil {
		h.writeError(w, http.StatusServiceUnavailable, "unavailable", "command service is unavailable")
		return
	}
	id := strings.TrimPrefix(r.URL.Path, "/api/v1/commands/")
	if id == "" {
		h.writeError(w, http.StatusNotFound, "not_found", "command not found")
		return
	}
	if r.Method == http.MethodGet {
		record, err := h.CommandService.Store.GetCommand(r.Context(), id)
		if err != nil {
			h.writeError(w, http.StatusNotFound, "not_found", err.Error())
			return
		}
		h.write(w, http.StatusOK, 0, "success", record)
		return
	}
	if r.Method == http.MethodPost && strings.HasSuffix(id, "/cancel") {
		id = strings.TrimSuffix(id, "/cancel")
		ok, err := h.CommandService.Store.CancelCommand(r.Context(), id, time.Now().UnixMilli())
		if err != nil {
			h.writeError(w, http.StatusInternalServerError, "storage_error", err.Error())
			return
		}
		if !ok {
			h.writeError(w, http.StatusConflict, "too_late_to_cancel", "command was already dispatched")
			return
		}
		h.write(w, http.StatusOK, 0, "success", map[string]any{"command_id": id, "status": protocol.StatusCancelled})
		return
	}
	h.writeError(w, http.StatusMethodNotAllowed, "method_not_allowed", "method is not supported")
}
func (h *Handler) admitCommand(w http.ResponseWriter, r *http.Request) {
	defer r.Body.Close()
	var intent protocol.ImmutableIntent
	if err := decodeJSON(w, r, &intent, h.MaxBodyBytes); err != nil {
		h.writeError(w, http.StatusBadRequest, "invalid_request", err.Error())
		return
	}
	identity, authenticated := security.AuthenticatedIdentity(r.Context())
	if !authenticated {
		h.writeError(w, http.StatusUnauthorized, "unauthorized", "authenticated identity is unavailable")
		return
	}
	if intent.IssuerID != "" && intent.IssuerID != identity {
		h.writeError(w, http.StatusForbidden, "issuer_mismatch", "request issuer does not match authenticated identity")
		return
	}
	intent.IssuerID = identity
	hash, err := protocol.CanonicalHash(intent)
	if err != nil {
		h.writeError(w, http.StatusBadRequest, "invalid_intent", err.Error())
		return
	}
	record, fresh, err := h.CommandService.Admit(r.Context(), intent, hash)
	if err != nil {
		if strings.Contains(err.Error(), "conflicts") {
			h.writeError(w, http.StatusConflict, "intent_conflict", err.Error())
		} else {
			h.writeError(w, http.StatusBadRequest, "admission_failed", err.Error())
		}
		return
	}
	if fresh && h.CommandService.Hold != nil && h.CommandService.HoldPhase == "admitted" {
		h.CommandService.Hold(intent.CommandID, h.CommandService.HoldPhase, h.CommandService.HoldDir)
	}
	if fresh && intent.ExecuteBeforeAtMS > 0 && intent.ExecuteBeforeAtMS <= time.Now().UnixMilli() {
		if _, err := h.CommandService.Store.ExpireCommand(r.Context(), intent.CommandID, time.Now().UnixMilli()); err != nil {
			h.writeError(w, http.StatusInternalServerError, "storage_error", err.Error())
			return
		}
		record, _ = h.CommandService.Store.GetCommand(r.Context(), intent.CommandID)
		h.write(w, http.StatusAccepted, 0, "success", record)
		return
	}
	if fresh && h.CommandService.Transport != nil {
		if err := h.CommandService.Dispatch(r.Context(), intent, hash, security.NewRequestID()); err != nil {
			if strings.Contains(err.Error(), "no longer dispatchable") {
				h.writeError(w, http.StatusConflict, "too_late_to_dispatch", err.Error())
			} else {
				h.writeError(w, http.StatusServiceUnavailable, "endpoint_unavailable", err.Error())
			}
			return
		}
	}
	status := http.StatusOK
	if fresh {
		status = http.StatusAccepted
	}
	h.write(w, status, 0, "success", record)
}

func parseCommandLimit(value string) int {
	n, err := strconv.Atoi(value)
	if err != nil || n <= 0 {
		return 20
	}
	if n > 100 {
		return 100
	}
	return n
}
