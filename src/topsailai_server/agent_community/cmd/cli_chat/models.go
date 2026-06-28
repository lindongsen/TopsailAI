// Package main contains shared data models for the ACS chat CLI.
package main

// Response is the standard API response envelope.
type Response[T any] struct {
	Data    T      `json:"data"`
	Error   string `json:"error"`
	TraceID string `json:"trace_id"`
}

// ListResponse is the standard list API response envelope.
type ListResponse[T any] struct {
	Items  []T `json:"items"`
	Total  int `json:"total"`
	Offset int `json:"offset"`
	Limit  int `json:"limit"`
}

// Account represents an ACS account.
type Account struct {
	AccountID   string `json:"account_id"`
	AccountName string `json:"account_name"`
	Role        string `json:"role"`
	Status      string `json:"status"`
	LoginName   string `json:"login_name"`
}

// LoginResponse is returned by the login endpoint.
type LoginResponse struct {
	AccountID   string `json:"account_id"`
	SessionKey  string `json:"session_key"`
	ExpiresAtMs int64  `json:"expires_at_ms"`
}

// Group represents an ACS group.
type Group struct {
	GroupID      string `json:"group_id"`
	GroupName    string `json:"group_name"`
	GroupContext string `json:"group_context"`
	GroupKey     string `json:"group_key"`
	CreatorID    string `json:"creator_id"`
	OwnerID      string `json:"owner_id"`
	CreateAtMs   int64  `json:"create_at_ms"`
	UpdateAtMs   int64  `json:"update_at_ms"`
}

// CreateGroupRequest is the body for creating a group.
type CreateGroupRequest struct {
	GroupName    string `json:"group_name"`
	GroupContext string `json:"group_context"`
	GroupKey     string `json:"group_key,omitempty"`
}

// Member represents a group member.
type Member struct {
	GroupID           string `json:"group_id"`
	MemberID          string `json:"member_id"`
	MemberName        string `json:"member_name"`
	MemberDescription string `json:"member_description"`
	MemberStatus      string `json:"member_status"`
	MemberType        string `json:"member_type"`
	MemberInterface   any    `json:"member_interface"`
	LastReadMessageID string `json:"last_read_message_id"`
	CreateAtMs        int64  `json:"create_at_ms"`
	UpdateAtMs        int64  `json:"update_at_ms"`
}

// AddMemberRequest is the body for adding a member.
type AddMemberRequest struct {
	MemberID            string `json:"member_id"`
	MemberName          string `json:"member_name"`
	MemberDescription   string `json:"member_description,omitempty"`
	MemberType          string `json:"member_type"`
	MemberInterface     any    `json:"member_interface,omitempty"`
}

// Message represents a group message.
type Message struct {
	MessageID          string `json:"message_id"`
	GroupID            string `json:"group_id"`
	MessageText        string `json:"message_text"`
	MessageAttachments []any  `json:"message_attachments"`
	SenderID           string `json:"sender_id"`
	SenderName         string `json:"sender_name"`
	SenderType         string `json:"sender_type"`
	ProcessedMsgID     string `json:"processed_msg_id"`
	Mentions           []any  `json:"mentions"`
	IsDeleted          bool   `json:"is_deleted"`
	DeleteAtMs         int64  `json:"delete_at_ms"`
	CreateAtMs         int64  `json:"create_at_ms"`
	UpdateAtMs         int64  `json:"update_at_ms"`
}

// SendMessageRequest is the body for sending a message.
type SendMessageRequest struct {
	MessageText        string `json:"message_text"`
	MessageAttachments []any  `json:"message_attachments,omitempty"`
}
