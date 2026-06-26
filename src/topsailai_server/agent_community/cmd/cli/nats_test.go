// Package main provides unit tests for the CLI NATS manager.
package main

import (
	"encoding/json"
	"errors"
	"net/http"
	"net/http/httptest"
	"sync"
	"testing"
	"time"

	natspkg "github.com/nats-io/nats.go"
	"github.com/topsailai/agent-community/internal/nats"
)

// fakeNATSConn is a test double for natsConn.
type fakeNATSConn struct {
	mu           sync.Mutex
	subscribeErr error
	subscribed   []subCall
	closed       bool
	js           natspkg.JetStreamContext
}

type subCall struct {
	subj string
	cb   natspkg.MsgHandler
}

func (f *fakeNATSConn) Subscribe(subj string, cb natspkg.MsgHandler) (*natspkg.Subscription, error) {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.subscribeErr != nil {
		return nil, f.subscribeErr
	}
	f.subscribed = append(f.subscribed, subCall{subj: subj, cb: cb})
	return &natspkg.Subscription{}, nil
}

func (f *fakeNATSConn) JetStream(opts ...natspkg.JSOpt) (natspkg.JetStreamContext, error) {
	return f.js, nil
}

func (f *fakeNATSConn) Close() {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.closed = true
}

func (f *fakeNATSConn) IsClosed() bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.closed
}

// fakeGroupSubscriber is a test double for groupSubscriber.
type fakeGroupSubscriber struct {
	mu           sync.Mutex
	subscribed   []string
	unsubscribed bool
	subscribeErr error
}

func (f *fakeGroupSubscriber) SubscribeGroup(groupID string) error {
	f.mu.Lock()
	defer f.mu.Unlock()
	if f.subscribeErr != nil {
		return f.subscribeErr
	}
	f.subscribed = append(f.subscribed, groupID)
	return nil
}

func (f *fakeGroupSubscriber) Unsubscribe() error {
	f.mu.Lock()
	defer f.mu.Unlock()
	f.unsubscribed = true
	return nil
}

func (f *fakeGroupSubscriber) IsSubscribed(groupID string) bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	for _, g := range f.subscribed {
		if g == groupID {
			return true
		}
	}
	return false
}

func (f *fakeGroupSubscriber) WasUnsubscribed() bool {
	f.mu.Lock()
	defer f.mu.Unlock()
	return f.unsubscribed
}

func newTestAPIClient() *APIClient {
	return NewAPIClient("http://localhost:99999")
}

func TestNATSManager_New(t *testing.T) {
	apiClient := newTestAPIClient()
	onEvent := func(*nats.PendingPublishMessage) {}

	m := NewNATSManager(apiClient, onEvent)
	if m == nil {
		t.Fatal("NewNATSManager() returned nil")
	}
	if m.apiClient != apiClient {
		t.Error("apiClient not set correctly")
	}
	if m.GetOnEvent() == nil {
		t.Error("onEvent not set correctly")
	}
	if m.instanceID == "" {
		t.Error("instanceID should be generated")
	}
}

func TestNATSManager_SetGetOnEvent(t *testing.T) {
	m := NewNATSManager(newTestAPIClient(), nil)

	called := false
	handler := func(*nats.PendingPublishMessage) { called = true }

	m.SetOnEvent(handler)
	got := m.GetOnEvent()
	if got == nil {
		t.Fatal("GetOnEvent() returned nil")
	}
	got(nil)
	if !called {
		t.Error("retrieved handler was not the one set")
	}
}

func TestNATSManager_Connect_Success(t *testing.T) {
	m := NewNATSManager(newTestAPIClient(), nil)
	fakeConn := &fakeNATSConn{}

	m.connectFn = func() (natsConn, error) {
		return fakeConn, nil
	}
	m.newSubscriberFn = func(js natspkg.JetStreamContext, handler nats.MessageHandler, instanceID string) groupSubscriber {
		return &fakeGroupSubscriber{}
	}

	if err := m.Connect(); err != nil {
		t.Fatalf("Connect() error = %v", err)
	}
	if !m.IsConnected() {
		t.Error("IsConnected() = false, want true")
	}
	if m.nc != fakeConn {
		t.Error("nc was not set to the connected connection")
	}
}

func TestNATSManager_Connect_Failure(t *testing.T) {
	m := NewNATSManager(newTestAPIClient(), nil)

	wantErr := errors.New("connection refused")
	m.connectFn = func() (natsConn, error) {
		return nil, wantErr
	}

	err := m.Connect()
	if err == nil {
		t.Fatal("Connect() expected error, got nil")
	}
	if !errors.Is(err, wantErr) {
		t.Errorf("Connect() error = %v, want %v", err, wantErr)
	}
	if m.IsConnected() {
		t.Error("IsConnected() = true, want false")
	}
}

func TestNATSManager_SubscribeGroup_Success(t *testing.T) {
	m := NewNATSManager(newTestAPIClient(), nil)
	fakeConn := &fakeNATSConn{}
	fakeSub := &fakeGroupSubscriber{}

	m.connectFn = func() (natsConn, error) {
		return fakeConn, nil
	}
	m.newSubscriberFn = func(js natspkg.JetStreamContext, handler nats.MessageHandler, instanceID string) groupSubscriber {
		return fakeSub
	}

	if err := m.Connect(); err != nil {
		t.Fatalf("Connect() error = %v", err)
	}

	groupID := "group-123"
	if err := m.SubscribeGroup(groupID); err != nil {
		t.Fatalf("SubscribeGroup() error = %v", err)
	}

	if !fakeSub.IsSubscribed(groupID) {
		t.Errorf("SubscribeGroup(%q) was not called on subscriber", groupID)
	}
	if m.groupID != groupID {
		t.Errorf("groupID = %q, want %q", m.groupID, groupID)
	}
}

func TestNATSManager_SubscribeGroup_NotConnected(t *testing.T) {
	m := NewNATSManager(newTestAPIClient(), nil)

	groupID := "group-123"
	if err := m.SubscribeGroup(groupID); err != nil {
		t.Fatalf("SubscribeGroup() error = %v", err)
	}

	if m.groupID != groupID {
		t.Errorf("groupID = %q, want %q", m.groupID, groupID)
	}
	if m.cancelPoll == nil {
		t.Fatal("expected HTTP polling to be started (cancelPoll should be set)")
	}

	// Clean up polling goroutine.
	_ = m.Unsubscribe()
}

func TestNATSManager_Unsubscribe(t *testing.T) {
	m := NewNATSManager(newTestAPIClient(), nil)
	fakeSub := &fakeGroupSubscriber{}

	m.connectFn = func() (natsConn, error) {
		return &fakeNATSConn{}, nil
	}
	m.newSubscriberFn = func(js natspkg.JetStreamContext, handler nats.MessageHandler, instanceID string) groupSubscriber {
		return fakeSub
	}

	if err := m.Connect(); err != nil {
		t.Fatalf("Connect() error = %v", err)
	}
	if err := m.SubscribeGroup("group-123"); err != nil {
		t.Fatalf("SubscribeGroup() error = %v", err)
	}

	if err := m.Unsubscribe(); err != nil {
		t.Fatalf("Unsubscribe() error = %v", err)
	}

	if !fakeSub.WasUnsubscribed() {
		t.Error("subscriber.Unsubscribe() was not called")
	}
	if m.cancelPoll != nil {
		t.Error("expected polling cancel func to be cleared")
	}
	if m.groupID != "" {
		t.Errorf("groupID = %q, want empty", m.groupID)
	}
}

func TestNATSManager_Close(t *testing.T) {
	m := NewNATSManager(newTestAPIClient(), nil)
	fakeConn := &fakeNATSConn{}
	fakeSub := &fakeGroupSubscriber{}

	m.connectFn = func() (natsConn, error) {
		return fakeConn, nil
	}
	m.newSubscriberFn = func(js natspkg.JetStreamContext, handler nats.MessageHandler, instanceID string) groupSubscriber {
		return fakeSub
	}

	if err := m.Connect(); err != nil {
		t.Fatalf("Connect() error = %v", err)
	}
	if err := m.SubscribeGroup("group-123"); err != nil {
		t.Fatalf("SubscribeGroup() error = %v", err)
	}

	m.Close()

	if m.IsConnected() {
		t.Error("IsConnected() = true after Close, want false")
	}
	if !fakeConn.IsClosed() {
		t.Error("connection Close() was not called")
	}
	if !fakeSub.WasUnsubscribed() {
		t.Error("subscriber.Unsubscribe() was not called during Close")
	}
}

// TestNATSManager_SubscribeGroup_SubscriberError verifies that a NATS
// subscription error falls back to HTTP polling.
func TestNATSManager_SubscribeGroup_SubscriberError(t *testing.T) {
	m := NewNATSManager(newTestAPIClient(), nil)
	fakeSub := &fakeGroupSubscriber{subscribeErr: errors.New("subscribe failed")}

	m.connectFn = func() (natsConn, error) {
		return &fakeNATSConn{}, nil
	}
	m.newSubscriberFn = func(js natspkg.JetStreamContext, handler nats.MessageHandler, instanceID string) groupSubscriber {
		return fakeSub
	}

	if err := m.Connect(); err != nil {
		t.Fatalf("Connect() error = %v", err)
	}

	groupID := "group-123"
	if err := m.SubscribeGroup(groupID); err != nil {
		t.Fatalf("SubscribeGroup() error = %v", err)
	}

	if m.cancelPoll == nil {
		t.Error("expected HTTP polling fallback to be started after subscriber error")
	}

	_ = m.Unsubscribe()
}

// TestNATSManager_SubscribeGroup_ResubscribeStopsPolling verifies that
// re-subscribing stops an existing polling goroutine before starting a new one.
func TestNATSManager_SubscribeGroup_ResubscribeStopsPolling(t *testing.T) {
	m := NewNATSManager(newTestAPIClient(), nil)

	if err := m.SubscribeGroup("group-123"); err != nil {
		t.Fatalf("SubscribeGroup() error = %v", err)
	}
	if m.cancelPoll == nil {
		t.Fatal("expected polling to be started")
	}

	if err := m.SubscribeGroup("group-456"); err != nil {
		t.Fatalf("SubscribeGroup() error = %v", err)
	}

	if m.groupID != "group-456" {
		t.Errorf("groupID = %q, want group-456", m.groupID)
	}
	if m.cancelPoll == nil {
		t.Fatal("expected a new polling cancel func after re-subscription")
	}

	_ = m.Unsubscribe()
}

// TestNATSManager_Connect_JetStreamFailure verifies that a JetStream creation
// failure closes the connection and reports an error.
func TestNATSManager_Connect_JetStreamFailure(t *testing.T) {
	wantErr := errors.New("jetstream unavailable")
	customConn := &fakeNATSConnWithJetStreamErr{err: wantErr}

	m := NewNATSManager(newTestAPIClient(), nil)
	m.connectFn = func() (natsConn, error) {
		return customConn, nil
	}

	err := m.Connect()
	if err == nil {
		t.Fatal("Connect() expected error, got nil")
	}
	if !errors.Is(err, wantErr) {
		t.Errorf("Connect() error = %v, want %v", err, wantErr)
	}
	if m.IsConnected() {
		t.Error("IsConnected() = true, want false")
	}
	if !customConn.closed {
		t.Error("expected connection to be closed after JetStream failure")
	}
}

// fakeNATSConnWithJetStreamErr is a conn that fails JetStream creation.
type fakeNATSConnWithJetStreamErr struct {
	fakeNATSConn
	err error
}

func (f *fakeNATSConnWithJetStreamErr) JetStream(opts ...natspkg.JSOpt) (natspkg.JetStreamContext, error) {
	return nil, f.err
}

// TestNATSManager_EventHandlerDispatch verifies that the handler installed by
// Connect dispatches events to the manager's onEvent callback.
func TestNATSManager_EventHandlerDispatch(t *testing.T) {
	m := NewNATSManager(newTestAPIClient(), nil)

	var received *nats.PendingPublishMessage
	m.onEvent = func(msg *nats.PendingPublishMessage) {
		received = msg
	}

	var capturedHandler nats.MessageHandler
	fakeSub := &fakeGroupSubscriber{}

	m.connectFn = func() (natsConn, error) {
		return &fakeNATSConn{}, nil
	}
	m.newSubscriberFn = func(js natspkg.JetStreamContext, handler nats.MessageHandler, instanceID string) groupSubscriber {
		capturedHandler = handler
		return fakeSub
	}

	if err := m.Connect(); err != nil {
		t.Fatalf("Connect() error = %v", err)
	}
	if capturedHandler == nil {
		t.Fatal("expected subscriber handler to be captured")
	}

	sent := &nats.PendingPublishMessage{Type: "message", GroupID: "g1"}
	if err := capturedHandler(sent); err != nil {
		t.Fatalf("handler error = %v", err)
	}

	if received != sent {
		t.Error("onEvent was not invoked with the expected message")
	}
}

// TestNATSManager_PollingStop verifies that the polling goroutine can be
// stopped cleanly without races.
func TestNATSManager_PollingStop(t *testing.T) {
	m := NewNATSManager(newTestAPIClient(), nil)

	if err := m.SubscribeGroup("group-123"); err != nil {
		t.Fatalf("SubscribeGroup() error = %v", err)
	}

	done := make(chan struct{})
	go func() {
		_ = m.Unsubscribe()
		close(done)
	}()

	select {
	case <-done:
		// ok
	case <-time.After(2 * time.Second):
		t.Fatal("Unsubscribe did not stop polling in time")
	}

	if m.cancelPoll != nil {
		t.Error("expected cancelPoll to be nil after Unsubscribe")
	}
}

// pollMessagesTestServer returns an httptest.Server that responds to
// /api/v1/groups/{groupID}/messages with the provided payload.
func pollMessagesTestServer(t *testing.T, payload interface{}) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodGet {
			http.Error(w, "method not allowed", http.StatusMethodNotAllowed)
			return
		}
		w.Header().Set("Content-Type", "application/json")
		_ = json.NewEncoder(w).Encode(payload)
	}))
}

func TestNATSManager_PollMessages_DispatchesEvents(t *testing.T) {
	groupID := "group-123"
	// API default order is newest-first; pollMessages emits oldest-first.
	messages := []map[string]interface{}{
		{"message_id": "msg-2", "message_text": "world", "create_at_ms": float64(2000)},
		{"message_id": "msg-1", "message_text": "hello", "create_at_ms": float64(1000)},
	}
	server := pollMessagesTestServer(t, map[string]interface{}{
		"data": map[string]interface{}{"items": messages},
	})
	defer server.Close()

	m := NewNATSManager(NewAPIClient(server.URL), nil)

	var events []*nats.PendingPublishMessage
	m.onEvent = func(msg *nats.PendingPublishMessage) {
		events = append(events, msg)
	}
	m.pollMessages(groupID)

	if len(events) != 2 {
		t.Fatalf("expected 2 events, got %d", len(events))
	}
	if events[0].Data.(map[string]interface{})["message_id"] != "msg-1" {
		t.Error("first event should be the oldest message")
	}
	if events[1].Data.(map[string]interface{})["message_id"] != "msg-2" {
		t.Error("second event should be the second oldest message")
	}
	if m.lastPollTime != 2000 {
		t.Errorf("lastPollTime = %d, want 2000", m.lastPollTime)
	}
}

func TestNATSManager_PollMessages_DeduplicatesByTime(t *testing.T) {
	groupID := "group-123"
	messages := []map[string]interface{}{
		{"message_id": "msg-1", "message_text": "hello", "create_at_ms": float64(1000)},
		{"message_id": "msg-2", "message_text": "world", "create_at_ms": float64(2000)},
	}
	server := pollMessagesTestServer(t, map[string]interface{}{
		"data": map[string]interface{}{"items": messages},
	})
	defer server.Close()

	m := NewNATSManager(NewAPIClient(server.URL), nil)
	m.lastPollTime = 1500

	var events []*nats.PendingPublishMessage
	m.onEvent = func(msg *nats.PendingPublishMessage) {
		events = append(events, msg)
	}

	m.pollMessages(groupID)

	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
	if events[0].Data.(map[string]interface{})["message_id"] != "msg-2" {
		t.Error("expected only msg-2 to be dispatched")
	}
}

func TestNATSManager_PollMessages_EmptyItems(t *testing.T) {
	server := pollMessagesTestServer(t, map[string]interface{}{
		"data": map[string]interface{}{"items": []map[string]interface{}{}},
	})
	defer server.Close()

	m := NewNATSManager(NewAPIClient(server.URL), nil)
	var events []*nats.PendingPublishMessage
	m.onEvent = func(msg *nats.PendingPublishMessage) {
		events = append(events, msg)
	}

	m.pollMessages("group-123")

	if len(events) != 0 {
		t.Fatalf("expected 0 events, got %d", len(events))
	}
}

func TestNATSManager_PollMessages_APIError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		http.Error(w, "internal server error", http.StatusInternalServerError)
	}))
	defer server.Close()

	m := NewNATSManager(NewAPIClient(server.URL), nil)
	var events []*nats.PendingPublishMessage
	m.onEvent = func(msg *nats.PendingPublishMessage) {
		events = append(events, msg)
	}

	m.pollMessages("group-123")

	if len(events) != 0 {
		t.Fatalf("expected 0 events on API error, got %d", len(events))
	}
}

func TestNATSManager_PollMessages_SkipsMissingMessageID(t *testing.T) {
	messages := []map[string]interface{}{
		{"message_text": "no id", "create_at_ms": float64(1000)},
		{"message_id": "msg-2", "message_text": "has id", "create_at_ms": float64(2000)},
	}
	server := pollMessagesTestServer(t, map[string]interface{}{
		"data": map[string]interface{}{"items": messages},
	})
	defer server.Close()

	m := NewNATSManager(NewAPIClient(server.URL), nil)
	var events []*nats.PendingPublishMessage
	m.onEvent = func(msg *nats.PendingPublishMessage) {
		events = append(events, msg)
	}

	m.pollMessages("group-123")

	if len(events) != 1 {
		t.Fatalf("expected 1 event, got %d", len(events))
	}
	if events[0].Data.(map[string]interface{})["message_id"] != "msg-2" {
		t.Error("expected msg-2 to be dispatched")
	}
}

// fakeJetStreamContext is a minimal test double for nats.JetStreamContext.
// No methods are invoked by the CLI NATS manager during Connect when the
// production subscriber factory is used, so the embedded interface is left nil.
type fakeJetStreamContext struct {
	natspkg.JetStreamContext
}

// TestNATSManager_Connect_ProductionSubscriberFactory verifies that Connect
// uses nats.NewSubscriber when newSubscriberFn is not injected.
func TestNATSManager_Connect_ProductionSubscriberFactory(t *testing.T) {
	m := NewNATSManager(newTestAPIClient(), nil)
	fakeConn := &fakeNATSConn{js: &fakeJetStreamContext{}}

	m.connectFn = func() (natsConn, error) {
		return fakeConn, nil
	}
	// newSubscriberFn intentionally nil to exercise production path.

	if err := m.Connect(); err != nil {
		t.Fatalf("Connect() error = %v", err)
	}
	if !m.IsConnected() {
		t.Error("IsConnected() = false, want true")
	}
	if m.subscriber == nil {
		t.Error("expected production subscriber to be created")
	}
}
