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
// A positive maxChars narrows one message body and is forwarded as a query
// parameter. Zero omits the parameter so the adapter's own default applies, which
// keeps an unset bound from being indistinguishable from an explicit request.
func (c *APIClient) GetMessages(ctx context.Context, endpointID, sessionID string, maxChars int) (protocol.MessagesResult, error) {
	var result protocol.MessagesResult
	path := "/api/v1/messages?endpoint_id=" + url.QueryEscape(endpointID) + "&session_id=" + url.QueryEscape(sessionID)
	if maxChars > 0 {
		path += "&max_chars=" + strconv.Itoa(maxChars)
	}
	err := c.get(ctx, path, &result)
	return result, err
}
