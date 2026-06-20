// Package nats provides NATS integration for the ACS service.
package nats

import (
	"encoding/json"
	"errors"
	"testing"

	"github.com/nats-io/nats.go"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// subscribeCall records a single call to the fake JetStream Subscribe method.
type subscribeCall struct {
	subject string
	handler nats.MsgHandler
	opts    []nats.SubOpt
}

// fakeSubscription is a test double for the internal subscription interface.
type fakeSubscription struct {
	unsubscribed bool
	unsubErr     error
}

func (f *fakeSubscription) Unsubscribe() error {
	f.unsubscribed = true
	return f.unsubErr
}

// fakeJetStreamSubscriber extends the publisher fake with Subscribe support.
type fakeJetStreamSubscriber struct {
	*fakeJetStream
	subscribeCalls []subscribeCall
	subscribeErr   error
}

func newFakeJetStreamSubscriber() *fakeJetStreamSubscriber {
	return &fakeJetStreamSubscriber{
		fakeJetStream: newFakeJetStream(),
	}
}

func (f *fakeJetStreamSubscriber) Subscribe(subj string, cb nats.MsgHandler, opts ...nats.SubOpt) (*nats.Subscription, error) {
	f.subscribeCalls = append(f.subscribeCalls, subscribeCall{subject: subj, handler: cb, opts: opts})
	if f.subscribeErr != nil {
		return nil, f.subscribeErr
	}
	// Return a non-nil *nats.Subscription. The Subscriber will not use it
	// directly because jsSubscribe is overridden in tests that exercise
	// Unsubscribe; otherwise the wrapper returns this value as a subscription.
	return &nats.Subscription{}, nil
}

// TestNewSubscriber verifies construction.
func TestNewSubscriber(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	var called bool
	handler := func(msg *PendingPublishMessage) error {
		called = true
		return nil
	}

	sub := NewSubscriber(fake, handler)
	require.NotNil(t, sub)
	assert.Equal(t, fake, sub.js)
	assert.NotNil(t, sub.handler)
	assert.Empty(t, sub.subs)
	assert.NotNil(t, sub.acker)
	assert.False(t, called)
}

// TestSubscriber_SubscribeGroup verifies subject, durable name and manual ack.
func TestSubscriber_SubscribeGroup(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	sub := NewSubscriber(fake, func(msg *PendingPublishMessage) error { return nil })

	err := sub.SubscribeGroup("group-abc")
	require.NoError(t, err)
	assert.True(t, sub.IsSubscribed())
	assert.Equal(t, 1, sub.SubscriptionCount())

	require.Len(t, fake.subscribeCalls, 1)
	call := fake.subscribeCalls[0]
	assert.Equal(t, "acs.group.message.group-abc", call.subject)
	assert.NotNil(t, call.handler)
	assert.Len(t, call.opts, 2) // Durable + ManualAck
}

// TestSubscriber_SubscribeGroup_Error verifies error wrapping on subscribe failure.
func TestSubscriber_SubscribeGroup_Error(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	fake.subscribeErr = errors.New("nats down")
	sub := NewSubscriber(fake, func(msg *PendingPublishMessage) error { return nil })

	err := sub.SubscribeGroup("group-abc")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to subscribe to group group-abc")
	assert.False(t, sub.IsSubscribed())
	assert.Equal(t, 0, sub.SubscriptionCount())
}

// TestSubscriber_SubscribeGroup_Dispatch verifies the callback invokes the handler and acks.
func TestSubscriber_SubscribeGroup_Dispatch(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	var received *PendingPublishMessage
	handler := func(msg *PendingPublishMessage) error {
		received = msg
		return nil
	}
	sub := NewSubscriber(fake, handler)

	var acked bool
	sub.acker = func(msg *nats.Msg) error { acked = true; return nil }

	err := sub.SubscribeGroup("group-abc")
	require.NoError(t, err)

	payload := PendingPublishMessage{
		Type:    "message",
		Action:  "create",
		GroupID: "group-abc",
		Data:    map[string]string{"message_id": "msg-1"},
	}
	data, _ := json.Marshal(payload)

	fake.subscribeCalls[0].handler(&nats.Msg{Data: data})

	require.NotNil(t, received)
	assert.Equal(t, "message", received.Type)
	assert.Equal(t, "create", received.Action)
	assert.Equal(t, "group-abc", received.GroupID)
	assert.True(t, acked)
}

// TestSubscriber_SubscribeGroup_HandlerError verifies handler errors are logged but still acked.
func TestSubscriber_SubscribeGroup_HandlerError(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	handler := func(msg *PendingPublishMessage) error {
		return errors.New("handler error")
	}
	sub := NewSubscriber(fake, handler)

	var acked bool
	sub.acker = func(msg *nats.Msg) error { acked = true; return nil }

	err := sub.SubscribeGroup("group-abc")
	require.NoError(t, err)

	payload := PendingPublishMessage{Type: "message", Action: "create", GroupID: "group-abc"}
	data, _ := json.Marshal(payload)
	fake.subscribeCalls[0].handler(&nats.Msg{Data: data})

	assert.True(t, acked)
}

// TestSubscriber_SubscribeGroup_UnmarshalError verifies unmarshal errors are logged but still acked.
func TestSubscriber_SubscribeGroup_UnmarshalError(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	sub := NewSubscriber(fake, func(msg *PendingPublishMessage) error { return nil })

	var acked bool
	sub.acker = func(msg *nats.Msg) error { acked = true; return nil }

	err := sub.SubscribeGroup("group-abc")
	require.NoError(t, err)

	fake.subscribeCalls[0].handler(&nats.Msg{Data: []byte("not json")})

	assert.True(t, acked)
}

// TestSubscriber_SubscribeGroups verifies subscribing to multiple groups.
func TestSubscriber_SubscribeGroups(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	sub := NewSubscriber(fake, func(msg *PendingPublishMessage) error { return nil })

	err := sub.SubscribeGroups([]string{"g1", "g2"})
	require.NoError(t, err)
	assert.Equal(t, 2, sub.SubscriptionCount())

	require.Len(t, fake.subscribeCalls, 2)
	assert.Equal(t, "acs.group.message.g1", fake.subscribeCalls[0].subject)
	assert.Equal(t, "acs.group.message.g2", fake.subscribeCalls[1].subject)
}

// TestSubscriber_SubscribeGroups_Error verifies first error is returned.
func TestSubscriber_SubscribeGroups_Error(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	fake.subscribeErr = errors.New("nats down")
	sub := NewSubscriber(fake, func(msg *PendingPublishMessage) error { return nil })

	err := sub.SubscribeGroups([]string{"g1", "g2"})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to subscribe to group g1")
	assert.Equal(t, 0, sub.SubscriptionCount())
}

// TestSubscriber_SubscribeAllGroups verifies wildcard subscription.
func TestSubscriber_SubscribeAllGroups(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	sub := NewSubscriber(fake, func(msg *PendingPublishMessage) error { return nil })

	err := sub.SubscribeAllGroups()
	require.NoError(t, err)
	assert.Equal(t, 1, sub.SubscriptionCount())

	require.Len(t, fake.subscribeCalls, 1)
	call := fake.subscribeCalls[0]
	assert.Equal(t, "acs.group.message.>", call.subject)
	assert.Len(t, call.opts, 2)
}

// TestSubscriber_SubscribeAllGroups_Error verifies error wrapping.
func TestSubscriber_SubscribeAllGroups_Error(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	fake.subscribeErr = errors.New("nats down")
	sub := NewSubscriber(fake, func(msg *PendingPublishMessage) error { return nil })

	err := sub.SubscribeAllGroups()
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to subscribe to all groups")
}

// TestSubscriber_SubscribePendingMessages verifies pending message subscription.
func TestSubscriber_SubscribePendingMessages(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	sub := NewSubscriber(fake, func(msg *PendingPublishMessage) error { return nil })

	err := sub.SubscribePendingMessages("group-abc")
	require.NoError(t, err)
	assert.Equal(t, 1, sub.SubscriptionCount())

	require.Len(t, fake.subscribeCalls, 1)
	call := fake.subscribeCalls[0]
	assert.Equal(t, "acs.group.pending-message.group-abc", call.subject)
	assert.Len(t, call.opts, 2)
}

// TestSubscriber_SubscribePendingMessages_Error verifies error wrapping.
func TestSubscriber_SubscribePendingMessages_Error(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	fake.subscribeErr = errors.New("nats down")
	sub := NewSubscriber(fake, func(msg *PendingPublishMessage) error { return nil })

	err := sub.SubscribePendingMessages("group-abc")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to subscribe to pending messages for group group-abc")
}

// TestSubscriber_SubscribePendingMessages_Dispatch verifies callback acks valid messages.
func TestSubscriber_SubscribePendingMessages_Dispatch(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	sub := NewSubscriber(fake, func(msg *PendingPublishMessage) error { return nil })

	var acked bool
	sub.acker = func(msg *nats.Msg) error { acked = true; return nil }

	err := sub.SubscribePendingMessages("group-abc")
	require.NoError(t, err)

	payload := PendingMessagePayload{Trigger: map[string]string{"type": "mention"}}
	data, _ := json.Marshal(payload)
	fake.subscribeCalls[0].handler(&nats.Msg{Data: data})

	assert.True(t, acked)
}

// TestSubscriber_SubscribeHeartbeats verifies heartbeat subscription and dispatch.
func TestSubscriber_SubscribeHeartbeats(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	var receivedNodeID string
	var receivedTimestamp int64
	handler := func(nodeID string, timestamp int64) {
		receivedNodeID = nodeID
		receivedTimestamp = timestamp
	}
	sub := NewSubscriber(fake, nil)

	var acked bool
	sub.acker = func(msg *nats.Msg) error { acked = true; return nil }

	err := sub.SubscribeHeartbeats(handler)
	require.NoError(t, err)
	assert.Equal(t, 1, sub.SubscriptionCount())

	require.Len(t, fake.subscribeCalls, 1)
	call := fake.subscribeCalls[0]
	assert.Equal(t, "acs.heartbeat", call.subject)
	assert.Len(t, call.opts, 2)

	data, _ := json.Marshal(map[string]interface{}{
		"node_id":   "node-1",
		"timestamp": int64(123456789),
		"status":    "healthy",
	})
	call.handler(&nats.Msg{Data: data})

	assert.Equal(t, "node-1", receivedNodeID)
	assert.Equal(t, int64(123456789), receivedTimestamp)
	assert.True(t, acked)
}

// TestSubscriber_SubscribeHeartbeats_UnmarshalError verifies invalid JSON is logged but acked.
func TestSubscriber_SubscribeHeartbeats_UnmarshalError(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	sub := NewSubscriber(fake, nil)

	var acked bool
	sub.acker = func(msg *nats.Msg) error { acked = true; return nil }

	err := sub.SubscribeHeartbeats(func(nodeID string, timestamp int64) {})
	require.NoError(t, err)

	fake.subscribeCalls[0].handler(&nats.Msg{Data: []byte("not json")})

	assert.True(t, acked)
}

// TestSubscriber_SubscribeHeartbeats_MissingFields verifies missing fields invoke handler with zero values.
func TestSubscriber_SubscribeHeartbeats_MissingFields(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	var receivedNodeID string
	var receivedTimestamp int64
	handler := func(nodeID string, timestamp int64) {
		receivedNodeID = nodeID
		receivedTimestamp = timestamp
	}
	sub := NewSubscriber(fake, nil)

	var acked bool
	sub.acker = func(msg *nats.Msg) error { acked = true; return nil }

	err := sub.SubscribeHeartbeats(handler)
	require.NoError(t, err)

	data, _ := json.Marshal(map[string]interface{}{"status": "healthy"})
	fake.subscribeCalls[0].handler(&nats.Msg{Data: data})

	assert.Equal(t, "", receivedNodeID)
	assert.Equal(t, int64(0), receivedTimestamp)
	assert.True(t, acked)
}

// TestSubscriber_SubscribeHeartbeats_Error verifies error wrapping on subscribe failure.
func TestSubscriber_SubscribeHeartbeats_Error(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	fake.subscribeErr = errors.New("nats down")
	sub := NewSubscriber(fake, nil)

	err := sub.SubscribeHeartbeats(func(nodeID string, timestamp int64) {})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to subscribe to heartbeats")
}

// TestSubscriber_Unsubscribe verifies unsubscribing from all active subscriptions.
func TestSubscriber_Unsubscribe(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	sub := NewSubscriber(fake, func(msg *PendingPublishMessage) error { return nil })

	fake1 := &fakeSubscription{}
	fake2 := &fakeSubscription{}
	original := jsSubscribe
	callCount := 0
	jsSubscribe = func(js nats.JetStreamContext, subj string, cb nats.MsgHandler, opts ...nats.SubOpt) (subscription, error) {
		callCount++
		if callCount == 1 {
			return fake1, nil
		}
		return fake2, nil
	}
	defer func() { jsSubscribe = original }()

	err := sub.SubscribeGroup("g1")
	require.NoError(t, err)
	err = sub.SubscribeGroup("g2")
	require.NoError(t, err)
	assert.Equal(t, 2, sub.SubscriptionCount())

	err = sub.Unsubscribe()
	require.NoError(t, err)
	assert.Equal(t, 0, sub.SubscriptionCount())
	assert.True(t, fake1.unsubscribed)
	assert.True(t, fake2.unsubscribed)
}

// TestSubscriber_Unsubscribe_WithError verifies unsubscribe errors are logged but processing continues.
func TestSubscriber_Unsubscribe_WithError(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	sub := NewSubscriber(fake, func(msg *PendingPublishMessage) error { return nil })

	fake1 := &fakeSubscription{unsubErr: errors.New("unsubscribe failed")}
	fake2 := &fakeSubscription{}
	original := jsSubscribe
	callCount := 0
	jsSubscribe = func(js nats.JetStreamContext, subj string, cb nats.MsgHandler, opts ...nats.SubOpt) (subscription, error) {
		callCount++
		if callCount == 1 {
			return fake1, nil
		}
		return fake2, nil
	}
	defer func() { jsSubscribe = original }()

	err := sub.SubscribeGroup("g1")
	require.NoError(t, err)
	err = sub.SubscribeGroup("g2")
	require.NoError(t, err)

	err = sub.Unsubscribe()
	require.NoError(t, err)
	assert.True(t, fake1.unsubscribed)
	assert.True(t, fake2.unsubscribed)
	assert.Equal(t, 0, sub.SubscriptionCount())
}

// TestSubscriber_IsSubscribed verifies subscription state lifecycle.
func TestSubscriber_IsSubscribed(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	sub := NewSubscriber(fake, func(msg *PendingPublishMessage) error { return nil })

	assert.False(t, sub.IsSubscribed())

	err := sub.SubscribeGroup("group-abc")
	require.NoError(t, err)
	assert.True(t, sub.IsSubscribed())

	err = sub.Unsubscribe()
	require.NoError(t, err)
	assert.False(t, sub.IsSubscribed())
}

// TestSubscriber_SubscriptionCount verifies count lifecycle.
func TestSubscriber_SubscriptionCount(t *testing.T) {
	fake := newFakeJetStreamSubscriber()
	sub := NewSubscriber(fake, func(msg *PendingPublishMessage) error { return nil })

	assert.Equal(t, 0, sub.SubscriptionCount())

	err := sub.SubscribeGroup("g1")
	require.NoError(t, err)
	assert.Equal(t, 1, sub.SubscriptionCount())

	err = sub.SubscribeGroup("g2")
	require.NoError(t, err)
	assert.Equal(t, 2, sub.SubscriptionCount())

	err = sub.Unsubscribe()
	require.NoError(t, err)
	assert.Equal(t, 0, sub.SubscriptionCount())
}
