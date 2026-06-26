// Package nats provides unit tests for the NATS subscriber.
package nats

import (
	"errors"
	"reflect"
	"strings"
	"testing"
	"unsafe"

	natspkg "github.com/nats-io/nats.go"
)

// fakeSubscription records whether Unsubscribe was called.
type fakeSubscription struct {
	unsubscribed bool
	unsubErr     error
}

func (f *fakeSubscription) Unsubscribe() error {
	f.unsubscribed = true
	return f.unsubErr
}

// fakeSubscriberJetStream records Subscribe calls so we can assert durable names.
type fakeSubscriberJetStream struct {
	natspkg.JetStreamContext
	subjects []string
	opts     [][]natspkg.SubOpt
	subErr   error
}

func (f *fakeSubscriberJetStream) Subscribe(subj string, cb natspkg.MsgHandler, opts ...natspkg.SubOpt) (*natspkg.Subscription, error) {
	if f.subErr != nil {
		return nil, f.subErr
	}
	f.subjects = append(f.subjects, subj)
	f.opts = append(f.opts, opts)
	return &natspkg.Subscription{}, nil
}

// containsDurable reports whether any SubOpt in opts sets the given durable name.
func containsDurable(opts []natspkg.SubOpt, name string) bool {
	for _, opt := range opts {
		if durableFromOpt(opt) == name {
			return true
		}
	}
	return false
}

// durableFromOpts returns the first non-empty durable name set by opts.
func durableFromOpts(opts []natspkg.SubOpt) string {
	for _, opt := range opts {
		if d := durableFromOpt(opt); d != "" {
			return d
		}
	}
	return ""
}

// durableFromOpt extracts the Durable consumer name from a nats.SubOpt by
// invoking it against a mirrored subOpts value. It returns "" for options that
// do not set Durable.
func durableFromOpt(opt natspkg.SubOpt) string {
	v := reflect.ValueOf(opt)
	if v.Kind() != reflect.Func || v.Type().NumIn() != 1 {
		return ""
	}
	natsSubOptsType := v.Type().In(0).Elem()
	ptr := reflect.New(natsSubOptsType)
	elem := ptr.Elem()
	cfgField := elem.FieldByName("cfg")
	cfgType := cfgField.Type().Elem()
	newCfg := reflect.New(cfgType)
	// subOpts.cfg is unexported; use unsafe to initialize the pointer so the
	// option function can write to opts.cfg.Durable.
	cfgPtr := (*unsafe.Pointer)(unsafe.Pointer(cfgField.UnsafeAddr()))
	*cfgPtr = unsafe.Pointer(newCfg.Pointer())
	res := v.Call([]reflect.Value{ptr})
	if !res[0].IsNil() {
		return ""
	}
	return newCfg.Elem().FieldByName("Durable").String()
}

func TestNewSubscriber_GeneratesInstanceID(t *testing.T) {
	js := &fakeSubscriberJetStream{}
	s := NewSubscriber(js, nil)
	if s.instanceID == "" {
		t.Fatal("expected generated instanceID")
	}
	if len(s.subs) != 0 {
		t.Errorf("expected 0 subscriptions, got %d", len(s.subs))
	}
}

func TestNewSubscriberWithInstanceID_UsesProvidedID(t *testing.T) {
	js := &fakeSubscriberJetStream{}
	s := NewSubscriberWithInstanceID(js, nil, "my-instance")
	if s.instanceID != "my-instance" {
		t.Errorf("instanceID = %q, want my-instance", s.instanceID)
	}
}

func TestNewSubscriberWithInstanceID_GeneratesWhenEmpty(t *testing.T) {
	js := &fakeSubscriberJetStream{}
	s := NewSubscriberWithInstanceID(js, nil, "")
	if s.instanceID == "" {
		t.Fatal("expected generated instanceID")
	}
}

func TestSubscriber_SubscribeGroup_DurableNameIncludesInstanceID(t *testing.T) {
	js := &fakeSubscriberJetStream{}
	s := NewSubscriberWithInstanceID(js, nil, "inst-1")

	if err := s.SubscribeGroup("group-123"); err != nil {
		t.Fatalf("SubscribeGroup() error = %v", err)
	}

	if len(js.subjects) != 1 {
		t.Fatalf("expected 1 subject, got %d", len(js.subjects))
	}
	if js.subjects[0] != groupMessageSubjectPrefix+"group-123" {
		t.Errorf("subject = %q, want %q", js.subjects[0], groupMessageSubjectPrefix+"group-123")
	}
	if len(js.opts) != 1 || len(js.opts[0]) != 2 {
		t.Fatalf("expected 1 call with 2 SubOpts, got %d calls / %d opts", len(js.opts), len(js.opts[0]))
	}
	wantDurable := "cli-group-123-inst-1"
	if !containsDurable(js.opts[0], wantDurable) {
		t.Errorf("durable options do not contain %q, got opts=%v", wantDurable, js.opts[0])
	}
}

func TestSubscriber_SubscribeAllGroups_DurableNameIncludesInstanceID(t *testing.T) {
	js := &fakeSubscriberJetStream{}
	s := NewSubscriberWithInstanceID(js, nil, "inst-2")

	if err := s.SubscribeAllGroups(); err != nil {
		t.Fatalf("SubscribeAllGroups() error = %v", err)
	}

	wantDurable := "cli-all-groups-inst-2"
	if !containsDurable(js.opts[0], wantDurable) {
		t.Errorf("durable options do not contain %q, got opts=%v", wantDurable, js.opts[0])
	}
}

func TestSubscriber_SubscribePendingMessages_DurableNameIncludesInstanceID(t *testing.T) {
	js := &fakeSubscriberJetStream{}
	s := NewSubscriberWithInstanceID(js, nil, "inst-3")

	if err := s.SubscribePendingMessages("group-456"); err != nil {
		t.Fatalf("SubscribePendingMessages() error = %v", err)
	}

	wantDurable := "pending-monitor-group-456-inst-3"
	if !containsDurable(js.opts[0], wantDurable) {
		t.Errorf("durable options do not contain %q, got opts=%v", wantDurable, js.opts[0])
	}
}

func TestSubscriber_SubscribeHeartbeats_DurableNameIncludesInstanceID(t *testing.T) {
	js := &fakeSubscriberJetStream{}
	s := NewSubscriberWithInstanceID(js, nil, "inst-4")

	if err := s.SubscribeHeartbeats(nil); err != nil {
		t.Fatalf("SubscribeHeartbeats() error = %v", err)
	}

	wantDurable := "heartbeat-monitor-inst-4"
	if !containsDurable(js.opts[0], wantDurable) {
		t.Errorf("durable options do not contain %q, got opts=%v", wantDurable, js.opts[0])
	}
}

func TestSubscriber_MultipleInstancesCanSubscribeSameGroup(t *testing.T) {
	js := &fakeSubscriberJetStream{}
	s1 := NewSubscriberWithInstanceID(js, nil, "inst-a")
	s2 := NewSubscriberWithInstanceID(js, nil, "inst-b")

	if err := s1.SubscribeGroup("group-shared"); err != nil {
		t.Fatalf("s1.SubscribeGroup() error = %v", err)
	}
	if err := s2.SubscribeGroup("group-shared"); err != nil {
		t.Fatalf("s2.SubscribeGroup() error = %v", err)
	}

	if len(js.opts) != 2 {
		t.Fatalf("expected 2 subscribe calls, got %d", len(js.opts))
	}
	d1 := durableFromOpts(js.opts[0])
	d2 := durableFromOpts(js.opts[1])
	if d1 == "" || d2 == "" {
		t.Fatalf("expected durable names, got d1=%q d2=%q", d1, d2)
	}
	if d1 == d2 {
		t.Errorf("durables should be unique, got %q and %q", d1, d2)
	}
	for _, d := range []string{d1, d2} {
		if !strings.HasPrefix(d, "cli-group-shared-") {
			t.Errorf("durable %q does not have expected prefix", d)
		}
	}
}

func TestSubscriber_SubscribeGroup_Error(t *testing.T) {
	wantErr := errors.New("nats unavailable")
	js := &fakeSubscriberJetStream{subErr: wantErr}
	s := NewSubscriberWithInstanceID(js, nil, "inst-err")

	err := s.SubscribeGroup("group-123")
	if err == nil {
		t.Fatal("expected error")
	}
	if !strings.Contains(err.Error(), "nats unavailable") {
		t.Errorf("error = %v, want containing 'nats unavailable'", err)
	}
}

func TestSubscriber_Unsubscribe(t *testing.T) {
	js := &fakeSubscriberJetStream{}
	s := NewSubscriberWithInstanceID(js, nil, "inst-unsub")

	// Replace jsSubscribe to return a fake subscription we can inspect.
	fakeSub := &fakeSubscription{}
	orig := jsSubscribe
	jsSubscribe = func(js natspkg.JetStreamContext, subj string, cb natspkg.MsgHandler, opts ...natspkg.SubOpt) (subscription, error) {
		return fakeSub, nil
	}
	defer func() { jsSubscribe = orig }()

	if err := s.SubscribeGroup("group-123"); err != nil {
		t.Fatalf("SubscribeGroup() error = %v", err)
	}
	if !s.IsSubscribed() {
		t.Fatal("expected subscriber to be subscribed")
	}

	if err := s.Unsubscribe(); err != nil {
		t.Fatalf("Unsubscribe() error = %v", err)
	}
	if s.IsSubscribed() {
		t.Error("expected subscriber to be unsubscribed")
	}
	if !fakeSub.unsubscribed {
		t.Error("expected fake subscription Unsubscribe to be called")
	}
}

func TestSubscriber_handleMessage(t *testing.T) {
	js := &fakeSubscriberJetStream{}

	var received *PendingPublishMessage
	handler := func(msg *PendingPublishMessage) error {
		received = msg
		return nil
	}
	s := NewSubscriberWithInstanceID(js, handler, "inst-msg")

	payload := []byte(`{"type":"message","action":"create","groupId":"g1","data":{"message_id":"m1"}}`)
	msg := &natspkg.Msg{Data: payload}
	if err := s.handleMessage(msg); err != nil {
		t.Fatalf("handleMessage() error = %v", err)
	}

	if received == nil {
		t.Fatal("handler was not called")
	}
	if received.Type != "message" || received.GroupID != "g1" {
		t.Errorf("received = %+v", received)
	}
}

func TestSubscriber_handleMessage_InvalidJSON(t *testing.T) {
	js := &fakeSubscriberJetStream{}
	s := NewSubscriberWithInstanceID(js, nil, "inst-msg")

	msg := &natspkg.Msg{Data: []byte("not-json")}
	err := s.handleMessage(msg)
	if err == nil {
		t.Fatal("expected error for invalid JSON")
	}
}

func TestSubscriber_handleMessage_HandlerError(t *testing.T) {
	js := &fakeSubscriberJetStream{}
	wantErr := errors.New("handler failed")
	handler := func(msg *PendingPublishMessage) error {
		return wantErr
	}
	s := NewSubscriberWithInstanceID(js, handler, "inst-msg")

	payload := []byte(`{"type":"message","action":"create","groupId":"g1"}`)
	msg := &natspkg.Msg{Data: payload}
	err := s.handleMessage(msg)
	if err == nil {
		t.Fatal("expected error from handler")
	}
	if !errors.Is(err, wantErr) {
		t.Errorf("error = %v, want %v", err, wantErr)
	}
}
