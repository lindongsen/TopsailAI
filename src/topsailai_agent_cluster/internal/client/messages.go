package client

import (
	"context"
	"net/url"
	"strconv"

	"topsailai_agent_cluster/internal/protocol"
)

// GetMessages reads one session's bounded conversation for one Endpoint.
//
// Messages are persisted provider data, so this call answers for a session that is
// no longer running. It is still a live provider read: the Server forwards the
// query and returns the adapter's answer verbatim, so the client never caches a
// result and never interprets provider role words.
//
// A positive maxChars or maxTokens narrows one message body and is forwarded as a
// query parameter. Zero omits the parameter so the adapter's own default applies,
// which keeps an unset bound from being indistinguishable from an explicit request.
// The two bounds are independent: a caller may state either, both, or neither, and
// the adapter applies whichever is tighter.
func (c *APIClient) GetMessages(ctx context.Context, endpointID, sessionID string, maxChars, maxTokens int) (protocol.MessagesResult, error) {
	var result protocol.MessagesResult
	path := "/api/v1/messages?endpoint_id=" + url.QueryEscape(endpointID) + "&session_id=" + url.QueryEscape(sessionID)
	if maxChars > 0 {
		path += "&max_chars=" + strconv.Itoa(maxChars)
	}
	if maxTokens > 0 {
		path += "&max_tokens=" + strconv.Itoa(maxTokens)
	}
	err := c.get(c.withEndpointToken(ctx, endpointID), path, &result)
	return result, c.explainRefusal(err, endpointID)
}
