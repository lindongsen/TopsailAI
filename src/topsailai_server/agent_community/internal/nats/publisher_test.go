// Package nats provides NATS integration for the ACS service.
package nats

import (
	"encoding/json"
	"errors"
	"testing"
	"time"

	"github.com/nats-io/nats.go"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"github.com/topsailai/agent-community/internal/models"
	"github.com/topsailai/agent-community/pkg/logger"
)

func init() {
	// Suppress logger output during publisher tests.
	logger.InitDefault(logger.Config{Output: "stdout", Level: "error"})
}

// publishCall records a single call to the fake JetStream Publish method.
type publishCall struct {
	subject string
	data    []byte
	opts    []nats.PubOpt
}

// fakeJetStream is a test double for nats.JetStreamContext.
// It records Publish calls and can be configured to return errors.
type fakeJetStream struct {
	calls        []publishCall
	publishErr   error
	publishAck   *nats.PubAck
}

func newFakeJetStream() *fakeJetStream {
	return &fakeJetStream{
		publishAck: &nats.PubAck{},
	}
}

func (f *fakeJetStream) Publish(subj string, data []byte, opts ...nats.PubOpt) (*nats.PubAck, error) {
	f.calls = append(f.calls, publishCall{subject: subj, data: data, opts: opts})
	if f.publishErr != nil {
		return nil, f.publishErr
	}
	return f.publishAck, nil
}

func (f *fakeJetStream) PublishMsg(m *nats.Msg, opts ...nats.PubOpt) (*nats.PubAck, error) {
	panic("not implemented")
}

func (f *fakeJetStream) PublishAsync(subj string, data []byte, opts ...nats.PubOpt) (nats.PubAckFuture, error) {
	panic("not implemented")
}

func (f *fakeJetStream) PublishMsgAsync(m *nats.Msg, opts ...nats.PubOpt) (nats.PubAckFuture, error) {
	panic("not implemented")
}

func (f *fakeJetStream) PublishAsyncPending() int {
	panic("not implemented")
}

func (f *fakeJetStream) PublishAsyncComplete() <-chan struct{} {
	panic("not implemented")
}

func (f *fakeJetStream) CleanupPublisher() {
	panic("not implemented")
}

func (f *fakeJetStream) Subscribe(subj string, cb nats.MsgHandler, opts ...nats.SubOpt) (*nats.Subscription, error) {
	panic("not implemented")
}

func (f *fakeJetStream) SubscribeSync(subj string, opts ...nats.SubOpt) (*nats.Subscription, error) {
	panic("not implemented")
}

func (f *fakeJetStream) ChanSubscribe(subj string, ch chan *nats.Msg, opts ...nats.SubOpt) (*nats.Subscription, error) {
	panic("not implemented")
}

func (f *fakeJetStream) ChanQueueSubscribe(subj, queue string, ch chan *nats.Msg, opts ...nats.SubOpt) (*nats.Subscription, error) {
	panic("not implemented")
}

func (f *fakeJetStream) QueueSubscribe(subj, queue string, cb nats.MsgHandler, opts ...nats.SubOpt) (*nats.Subscription, error) {
	panic("not implemented")
}

func (f *fakeJetStream) QueueSubscribeSync(subj, queue string, opts ...nats.SubOpt) (*nats.Subscription, error) {
	panic("not implemented")
}

func (f *fakeJetStream) PullSubscribe(subj, durable string, opts ...nats.SubOpt) (*nats.Subscription, error) {
	panic("not implemented")
}

func (f *fakeJetStream) AddStream(cfg *nats.StreamConfig, opts ...nats.JSOpt) (*nats.StreamInfo, error) {
	panic("not implemented")
}

func (f *fakeJetStream) UpdateStream(cfg *nats.StreamConfig, opts ...nats.JSOpt) (*nats.StreamInfo, error) {
	panic("not implemented")
}

func (f *fakeJetStream) DeleteStream(name string, opts ...nats.JSOpt) error {
	panic("not implemented")
}

func (f *fakeJetStream) StreamInfo(stream string, opts ...nats.JSOpt) (*nats.StreamInfo, error) {
	panic("not implemented")
}

func (f *fakeJetStream) PurgeStream(name string, opts ...nats.JSOpt) error {
	panic("not implemented")
}

func (f *fakeJetStream) StreamsInfo(opts ...nats.JSOpt) <-chan *nats.StreamInfo {
	panic("not implemented")
}

func (f *fakeJetStream) Streams(opts ...nats.JSOpt) <-chan *nats.StreamInfo {
	panic("not implemented")
}

func (f *fakeJetStream) StreamNames(opts ...nats.JSOpt) <-chan string {
	panic("not implemented")
}

func (f *fakeJetStream) GetMsg(name string, seq uint64, opts ...nats.JSOpt) (*nats.RawStreamMsg, error) {
	panic("not implemented")
}

func (f *fakeJetStream) GetLastMsg(name, subject string, opts ...nats.JSOpt) (*nats.RawStreamMsg, error) {
	panic("not implemented")
}

func (f *fakeJetStream) DeleteMsg(name string, seq uint64, opts ...nats.JSOpt) error {
	panic("not implemented")
}

func (f *fakeJetStream) SecureDeleteMsg(name string, seq uint64, opts ...nats.JSOpt) error {
	panic("not implemented")
}

func (f *fakeJetStream) AddConsumer(stream string, cfg *nats.ConsumerConfig, opts ...nats.JSOpt) (*nats.ConsumerInfo, error) {
	panic("not implemented")
}

func (f *fakeJetStream) UpdateConsumer(stream string, cfg *nats.ConsumerConfig, opts ...nats.JSOpt) (*nats.ConsumerInfo, error) {
	panic("not implemented")
}

func (f *fakeJetStream) DeleteConsumer(stream, consumer string, opts ...nats.JSOpt) error {
	panic("not implemented")
}

func (f *fakeJetStream) ConsumerInfo(stream, name string, opts ...nats.JSOpt) (*nats.ConsumerInfo, error) {
	panic("not implemented")
}

func (f *fakeJetStream) ConsumersInfo(stream string, opts ...nats.JSOpt) <-chan *nats.ConsumerInfo {
	panic("not implemented")
}

func (f *fakeJetStream) Consumers(stream string, opts ...nats.JSOpt) <-chan *nats.ConsumerInfo {
	panic("not implemented")
}

func (f *fakeJetStream) ConsumerNames(stream string, opts ...nats.JSOpt) <-chan string {
	panic("not implemented")
}

func (f *fakeJetStream) AccountInfo(opts ...nats.JSOpt) (*nats.AccountInfo, error) {
	panic("not implemented")
}

func (f *fakeJetStream) StreamNameBySubject(subject string, opts ...nats.JSOpt) (string, error) {
	panic("not implemented")
}

func (f *fakeJetStream) KeyValue(bucket string) (nats.KeyValue, error) {
	panic("not implemented")
}

func (f *fakeJetStream) CreateKeyValue(cfg *nats.KeyValueConfig) (nats.KeyValue, error) {
	panic("not implemented")
}

func (f *fakeJetStream) DeleteKeyValue(bucket string) error {
	panic("not implemented")
}

func (f *fakeJetStream) KeyValueStoreNames() <-chan string {
	panic("not implemented")
}

func (f *fakeJetStream) KeyValueStores() <-chan nats.KeyValueStatus {
	panic("not implemented")
}

func (f *fakeJetStream) ObjectStore(bucket string) (nats.ObjectStore, error) {
	panic("not implemented")
}

func (f *fakeJetStream) CreateObjectStore(cfg *nats.ObjectStoreConfig) (nats.ObjectStore, error) {
	panic("not implemented")
}

func (f *fakeJetStream) DeleteObjectStore(bucket string) error {
	panic("not implemented")
}

func (f *fakeJetStream) ObjectStoreNames(opts ...nats.ObjectOpt) <-chan string {
	panic("not implemented")
}

func (f *fakeJetStream) ObjectStores(opts ...nats.ObjectOpt) <-chan nats.ObjectStoreStatus {
	panic("not implemented")
}

// sampleMessage returns a minimal GroupMessage for testing.
func sampleMessage(groupID, messageID string) *models.GroupMessage {
	return &models.GroupMessage{
		GroupID:     groupID,
		MessageID:   messageID,
		MessageText: "hello",
		SenderID:    "user-1",
		SenderType:  models.MemberTypeUser,
		CreateAtMs:  time.Now().UnixMilli(),
		UpdateAtMs:  time.Now().UnixMilli(),
	}
}

// unmarshalPendingPayload unmarshals the published bytes into a pending message payload.
func unmarshalPendingPayload(t *testing.T, data []byte) PendingMessagePayload {
	t.Helper()
	var payload PendingMessagePayload
	require.NoError(t, json.Unmarshal(data, &payload))
	return payload
}

// unmarshalGroupEvent unmarshals the published bytes into a group event.
func unmarshalGroupEvent(t *testing.T, data []byte) PendingPublishMessage {
	t.Helper()
	var event PendingPublishMessage
	require.NoError(t, json.Unmarshal(data, &event))
	return event
}

func TestPublisher_PublishPendingMessage(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	msg := sampleMessage("group-abc", "msg-1")
	trigger := map[string]string{"type": "mention", "agent_id": "agent-1"}

	err := pub.PublishPendingMessage("group-abc", msg, trigger)
	require.NoError(t, err)
	require.Len(t, fake.calls, 1)

	call := fake.calls[0]
	assert.Equal(t, "acs.group.pending-message.group-abc", call.subject)
	assert.Len(t, call.opts, 1) // nats.MsgId

	payload := unmarshalPendingPayload(t, call.data)
	assert.Equal(t, msg.MessageID, payload.MessageID)
	assert.Equal(t, msg.MessageText, payload.MessageText)

	triggerMap, ok := payload.Trigger.(map[string]interface{})
	require.True(t, ok)
	assert.Equal(t, "mention", triggerMap["type"])
	assert.Equal(t, "agent-1", triggerMap["agent_id"])
}

func TestPublisher_PublishPendingMessage_MarshalError(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	msg := sampleMessage("group-abc", "msg-1")
	msg.MessageText = "valid" // reset to valid
	// Use a trigger value containing a channel, which cannot be marshaled.
	trigger := map[string]interface{}{"ch": make(chan int)}

	err := pub.PublishPendingMessage("group-abc", msg, trigger)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to marshal pending message")
	assert.Empty(t, fake.calls)
}

func TestPublisher_PublishPendingMessage_PublishError(t *testing.T) {
	fake := newFakeJetStream()
	fake.publishErr = errors.New("nats down")
	pub := NewPublisher(fake)

	msg := sampleMessage("group-abc", "msg-1")
	err := pub.PublishPendingMessage("group-abc", msg, nil)
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to publish pending message")
}

func TestPublisher_PublishGroupEvent(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	msg := sampleMessage("group-abc", "msg-1")
	err := pub.PublishGroupEvent("message", "create", "group-abc", msg)
	require.NoError(t, err)
	require.Len(t, fake.calls, 1)

	call := fake.calls[0]
	assert.Equal(t, "acs.group.message.group-abc", call.subject)
	assert.Empty(t, call.opts)

	event := unmarshalGroupEvent(t, call.data)
	assert.Equal(t, "message", event.Type)
	assert.Equal(t, "create", event.Action)
	assert.Equal(t, "group-abc", event.GroupID)

	dataMap, ok := event.Data.(map[string]interface{})
	require.True(t, ok)
	assert.Equal(t, msg.MessageID, dataMap["message_id"])
}

func TestPublisher_PublishGroupEvent_MarshalError(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	err := pub.PublishGroupEvent("message", "create", "group-abc", map[string]interface{}{"ch": make(chan int)})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to marshal group event")
	assert.Empty(t, fake.calls)
}

func TestPublisher_PublishGroupEvent_PublishError(t *testing.T) {
	fake := newFakeJetStream()
	fake.publishErr = errors.New("nats down")
	pub := NewPublisher(fake)

	err := pub.PublishGroupEvent("message", "create", "group-abc", map[string]string{"group_id": "group-abc"})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to publish group event")
}

func TestPublisher_PublishMessageCreate(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	msg := sampleMessage("group-abc", "msg-1")
	err := pub.PublishMessageCreate(msg)
	require.NoError(t, err)
	require.Len(t, fake.calls, 1)

	event := unmarshalGroupEvent(t, fake.calls[0].data)
	assert.Equal(t, "message", event.Type)
	assert.Equal(t, "create", event.Action)
}

func TestPublisher_PublishMessageModify(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	msg := sampleMessage("group-abc", "msg-1")
	err := pub.PublishMessageModify(msg)
	require.NoError(t, err)

	event := unmarshalGroupEvent(t, fake.calls[0].data)
	assert.Equal(t, "message", event.Type)
	assert.Equal(t, "modify", event.Action)
}

func TestPublisher_PublishMessageDelete(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	msg := sampleMessage("group-abc", "msg-1")
	err := pub.PublishMessageDelete(msg)
	require.NoError(t, err)

	event := unmarshalGroupEvent(t, fake.calls[0].data)
	assert.Equal(t, "message", event.Type)
	assert.Equal(t, "delete", event.Action)
}

func TestPublisher_PublishGroupCreate(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	group := &models.Group{GroupID: "group-abc", GroupName: "Test Group"}
	err := pub.PublishGroupCreate(group)
	require.NoError(t, err)

	event := unmarshalGroupEvent(t, fake.calls[0].data)
	assert.Equal(t, "group", event.Type)
	assert.Equal(t, "create", event.Action)
	dataMap := event.Data.(map[string]interface{})
	assert.Equal(t, "group-abc", dataMap["group_id"])
}

func TestPublisher_PublishGroupModify(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	group := &models.Group{GroupID: "group-abc", GroupName: "Test Group"}
	err := pub.PublishGroupModify(group)
	require.NoError(t, err)

	event := unmarshalGroupEvent(t, fake.calls[0].data)
	assert.Equal(t, "group", event.Type)
	assert.Equal(t, "modify", event.Action)
}

func TestPublisher_PublishGroupDelete(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	err := pub.PublishGroupDelete("group-abc")
	require.NoError(t, err)

	event := unmarshalGroupEvent(t, fake.calls[0].data)
	assert.Equal(t, "group", event.Type)
	assert.Equal(t, "delete", event.Action)
	dataMap := event.Data.(map[string]interface{})
	assert.Equal(t, "group-abc", dataMap["group_id"])
}

func TestPublisher_PublishGroupMemberCreate(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	member := &models.GroupMember{GroupID: "group-abc", MemberID: "user-1", MemberName: "Alice"}
	err := pub.PublishGroupMemberCreate(member)
	require.NoError(t, err)

	event := unmarshalGroupEvent(t, fake.calls[0].data)
	assert.Equal(t, "group_member", event.Type)
	assert.Equal(t, "create", event.Action)
}

func TestPublisher_PublishGroupMemberDelete(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	err := pub.PublishGroupMemberDelete("group-abc", "user-1")
	require.NoError(t, err)

	event := unmarshalGroupEvent(t, fake.calls[0].data)
	assert.Equal(t, "group_member", event.Type)
	assert.Equal(t, "delete", event.Action)
	dataMap := event.Data.(map[string]interface{})
	assert.Equal(t, "group-abc", dataMap["group_id"])
	assert.Equal(t, "user-1", dataMap["member_id"])
}

func TestPublisher_PublishGroupMemberModify(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	member := &models.GroupMember{GroupID: "group-abc", MemberID: "user-1", MemberName: "Alice"}
	err := pub.PublishGroupMemberModify(member)
	require.NoError(t, err)

	event := unmarshalGroupEvent(t, fake.calls[0].data)
	assert.Equal(t, "group_member", event.Type)
	assert.Equal(t, "modify", event.Action)
}

func TestPublisher_PublishAgentResponse(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	msg := sampleMessage("group-abc", "msg-1")
	err := pub.PublishAgentResponse(msg)
	require.NoError(t, err)

	event := unmarshalGroupEvent(t, fake.calls[0].data)
	assert.Equal(t, "message", event.Type)
	assert.Equal(t, "create", event.Action)
}

func TestPublisher_PublishSystemError(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	msg := sampleMessage("group-abc", "msg-1")
	err := pub.PublishSystemError(msg)
	require.NoError(t, err)

	event := unmarshalGroupEvent(t, fake.calls[0].data)
	assert.Equal(t, "message", event.Type)
	assert.Equal(t, "create", event.Action)
}

func TestPublisher_PublishAutoTriggerPendingMessage(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	msg := sampleMessage("group-abc", "msg-1")
	trigger := map[string]string{"type": "auto"}
	err := pub.PublishAutoTriggerPendingMessage("group-abc", msg, trigger)
	require.NoError(t, err)
	require.Len(t, fake.calls, 1)

	assert.Equal(t, "acs.group.pending-message.group-abc", fake.calls[0].subject)
	payload := unmarshalPendingPayload(t, fake.calls[0].data)
	triggerMap := payload.Trigger.(map[string]interface{})
	assert.Equal(t, "auto", triggerMap["type"])
}

func TestBuildMsgID(t *testing.T) {
	assert.Equal(t, "msg-1:agent-1", BuildMsgID("msg-1", "agent-1"))
}

func TestPublisher_PublishPendingMessageWithAgentID(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	msg := sampleMessage("group-abc", "msg-1")
	trigger := map[string]string{"type": "mention", "agent_id": "agent-1"}

	err := pub.PublishPendingMessageWithAgentID("group-abc", msg, trigger, "agent-1")
	require.NoError(t, err)
	require.Len(t, fake.calls, 1)

	call := fake.calls[0]
	assert.Equal(t, "acs.group.pending-message.group-abc", call.subject)
	assert.Len(t, call.opts, 1) // nats.MsgId("msg-1:agent-1")

	payload := unmarshalPendingPayload(t, call.data)
	assert.Equal(t, msg.MessageID, payload.MessageID)
}

func TestPublisher_PublishPendingMessageWithAgentID_MarshalError(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	msg := sampleMessage("group-abc", "msg-1")
	trigger := map[string]interface{}{"ch": make(chan int)}

	err := pub.PublishPendingMessageWithAgentID("group-abc", msg, trigger, "agent-1")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to marshal pending message")
}

func TestPublisher_PublishPendingMessageWithAgentID_PublishError(t *testing.T) {
	fake := newFakeJetStream()
	fake.publishErr = errors.New("nats down")
	pub := NewPublisher(fake)

	msg := sampleMessage("group-abc", "msg-1")
	err := pub.PublishPendingMessageWithAgentID("group-abc", msg, nil, "agent-1")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to publish pending message with agent id")
}

func TestPublisher_PublishHeartbeat(t *testing.T) {
	fake := newFakeJetStream()
	pub := NewPublisher(fake)

	err := pub.PublishHeartbeat("node-1")
	require.NoError(t, err)
	require.Len(t, fake.calls, 1)

	call := fake.calls[0]
	assert.Equal(t, "acs.heartbeat", call.subject)
	assert.Empty(t, call.opts)

	var payload map[string]interface{}
	require.NoError(t, json.Unmarshal(call.data, &payload))
	assert.Equal(t, "node-1", payload["node_id"])
	assert.Equal(t, "healthy", payload["status"])

	timestamp, ok := payload["timestamp"].(float64)
	require.True(t, ok)
	nowMs := time.Now().UnixMilli()
	assert.InDelta(t, nowMs, timestamp, 5000, "heartbeat timestamp should be near current time")
}

func TestPublisher_PublishHeartbeat_PublishError(t *testing.T) {
	fake := newFakeJetStream()
	fake.publishErr = errors.New("nats down")
	pub := NewPublisher(fake)

	err := pub.PublishHeartbeat("node-1")
	require.Error(t, err)
	assert.Contains(t, err.Error(), "failed to publish heartbeat")
}
