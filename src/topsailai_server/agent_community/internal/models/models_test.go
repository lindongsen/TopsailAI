// Package models defines GORM database model tests.
package models

import (
	"encoding/json"
	"regexp"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"gorm.io/driver/sqlite"
	"gorm.io/gorm"
)

// newTestDB returns a fresh in-memory SQLite GORM connection with all model tables auto-migrated.
func newTestDB(t *testing.T) *gorm.DB {
	t.Helper()
	db, err := gorm.Open(sqlite.Open("file::memory:?cache=shared"), &gorm.Config{})
	require.NoError(t, err)

	err = db.AutoMigrate(
		&Account{},
		&APIKey{},
		&AuditLog{},
		&Group{},
		&GroupMember{},
		&GroupMessage{},
		&AgentMessageProcessing{},
	)
	require.NoError(t, err)

	t.Cleanup(func() {
		sqlDB, err := db.DB()
		if err == nil && sqlDB != nil {
			_ = sqlDB.Close()
		}
	})
	return db
}

// idRegex returns a regex matching the documented ID prefix format.
func idRegex(prefix string) *regexp.Regexp {
	return regexp.MustCompile("^" + prefix + "[a-zA-Z0-9]+$")
}

// ==================== ID Generation Hooks ====================

func TestAccount_BeforeCreate_GeneratesID(t *testing.T) {
	db := newTestDB(t)
	acc := &Account{AccountName: "Alice", Role: AccountRoleUser, Status: AccountStatusActive, LoginName: "alice@example.com", CreatorID: "system"}
	require.NoError(t, db.Create(acc).Error)
	assert.Regexp(t, idRegex("acc-"), acc.AccountID)
}

func TestAccount_BeforeCreate_PreservesExistingID(t *testing.T) {
	db := newTestDB(t)
	acc := &Account{AccountID: "acc-existing", AccountName: "Alice", Role: AccountRoleUser, Status: AccountStatusActive, LoginName: "alice2@example.com", CreatorID: "system"}
	require.NoError(t, db.Create(acc).Error)
	assert.Equal(t, "acc-existing", acc.AccountID)
}

func TestAPIKey_BeforeCreate_GeneratesID(t *testing.T) {
	db := newTestDB(t)
	key := &APIKey{APIKeyName: "cli", Role: APIKeyRoleUser, Status: APIKeyStatusActive, CreatorID: "system", OwnerID: "acc-owner"}
	require.NoError(t, db.Create(key).Error)
	assert.Regexp(t, idRegex("ak-"), key.APIKeyID)
}

func TestAPIKey_BeforeCreate_PreservesExistingID(t *testing.T) {
	db := newTestDB(t)
	key := &APIKey{APIKeyID: "ak-existing", APIKeyName: "cli", Role: APIKeyRoleUser, Status: APIKeyStatusActive, CreatorID: "system", OwnerID: "acc-owner"}
	require.NoError(t, db.Create(key).Error)
	assert.Equal(t, "ak-existing", key.APIKeyID)
}

func TestAuditLog_BeforeCreate_GeneratesID(t *testing.T) {
	db := newTestDB(t)
	log := &AuditLog{AccountID: "acc-1", APIKeyID: "ak-1", Action: "create_account", ResourceType: "account", ResourceID: "acc-2"}
	require.NoError(t, db.Create(log).Error)
	assert.Regexp(t, idRegex("al-"), log.AuditLogID)
	assert.True(t, log.CreateAtMs > 0)
}

func TestAuditLog_BeforeCreate_PreservesExistingID(t *testing.T) {
	db := newTestDB(t)
	log := &AuditLog{AuditLogID: "al-existing", AccountID: "acc-1", APIKeyID: "ak-1", Action: "create_account", ResourceType: "account", ResourceID: "acc-2"}
	require.NoError(t, db.Create(log).Error)
	assert.Equal(t, "al-existing", log.AuditLogID)
}

func TestGroup_BeforeCreate_GeneratesID(t *testing.T) {
	db := newTestDB(t)
	g := &Group{GroupName: "Test Group", CreatorID: "acc-1", OwnerID: "acc-1"}
	require.NoError(t, db.Create(g).Error)
	assert.Regexp(t, idRegex("group-"), g.GroupID)
}

func TestGroup_BeforeCreate_PreservesExistingID(t *testing.T) {
	db := newTestDB(t)
	g := &Group{GroupID: "group-existing", GroupName: "Test Group", CreatorID: "acc-1", OwnerID: "acc-1"}
	require.NoError(t, db.Create(g).Error)
	assert.Equal(t, "group-existing", g.GroupID)
}

func TestGroupMessage_BeforeCreate_GeneratesID(t *testing.T) {
	db := newTestDB(t)
	msg := &GroupMessage{GroupID: "group-1", MessageText: "hello", SenderID: "user-1", SenderType: MemberTypeUser}
	require.NoError(t, db.Create(msg).Error)
	assert.Regexp(t, idRegex("msg-"), msg.MessageID)
}

func TestGroupMessage_BeforeCreate_PreservesExistingID(t *testing.T) {
	db := newTestDB(t)
	msg := &GroupMessage{GroupID: "group-1", MessageID: "msg-existing", MessageText: "hello", SenderID: "user-1", SenderType: MemberTypeUser}
	require.NoError(t, db.Create(msg).Error)
	assert.Equal(t, "msg-existing", msg.MessageID)
}

// ==================== Timestamp Hooks ====================

func TestAccount_Timestamps_SetOnCreate(t *testing.T) {
	db := newTestDB(t)
	before := time.Now().UnixMilli()
	acc := &Account{AccountName: "Alice", Role: AccountRoleUser, Status: AccountStatusActive, LoginName: "ts@example.com", CreatorID: "system"}
	require.NoError(t, db.Create(acc).Error)
	after := time.Now().UnixMilli()

	assert.GreaterOrEqual(t, acc.CreateAtMs, before)
	assert.LessOrEqual(t, acc.CreateAtMs, after)
	assert.Equal(t, acc.CreateAtMs, acc.UpdateAtMs)
}

func TestAccount_Timestamps_UpdateOnUpdate(t *testing.T) {
	db := newTestDB(t)
	acc := &Account{AccountName: "Alice", Role: AccountRoleUser, Status: AccountStatusActive, LoginName: "ts2@example.com", CreatorID: "system"}
	require.NoError(t, db.Create(acc).Error)
	oldUpdate := acc.UpdateAtMs

	time.Sleep(25 * time.Millisecond)
	acc.AccountName = "Alice Updated"
	require.NoError(t, db.Save(acc).Error)
	assert.Greater(t, acc.UpdateAtMs, oldUpdate)
}

func TestAPIKey_Timestamps(t *testing.T) {
	db := newTestDB(t)
	key := &APIKey{APIKeyName: "k", Role: APIKeyRoleUser, Status: APIKeyStatusActive, CreatorID: "system", OwnerID: "acc-1"}
	require.NoError(t, db.Create(key).Error)
	assert.True(t, key.CreateAtMs > 0)
	assert.Equal(t, key.CreateAtMs, key.UpdateAtMs)

	time.Sleep(25 * time.Millisecond)
	key.APIKeyName = "k2"
	require.NoError(t, db.Save(key).Error)
	assert.Greater(t, key.UpdateAtMs, key.CreateAtMs)
}

func TestGroup_Timestamps(t *testing.T) {
	db := newTestDB(t)
	g := &Group{GroupName: "G", CreatorID: "acc-1", OwnerID: "acc-1"}
	require.NoError(t, db.Create(g).Error)
	assert.True(t, g.CreateAtMs > 0)
	assert.Equal(t, g.CreateAtMs, g.UpdateAtMs)

	time.Sleep(25 * time.Millisecond)
	g.GroupName = "G2"
	require.NoError(t, db.Save(g).Error)
	assert.Greater(t, g.UpdateAtMs, g.CreateAtMs)
}

func TestGroupMember_Timestamps(t *testing.T) {
	db := newTestDB(t)
	gm := &GroupMember{GroupID: "group-1", MemberID: "member-1", MemberName: "M", MemberType: MemberTypeUser}
	require.NoError(t, db.Create(gm).Error)
	assert.True(t, gm.CreateAtMs > 0)
	assert.Equal(t, gm.CreateAtMs, gm.UpdateAtMs)

	time.Sleep(25 * time.Millisecond)
	gm.MemberName = "M2"
	require.NoError(t, db.Save(gm).Error)
	assert.Greater(t, gm.UpdateAtMs, gm.CreateAtMs)
}

func TestGroupMessage_Timestamps(t *testing.T) {
	db := newTestDB(t)
	msg := &GroupMessage{GroupID: "group-1", MessageText: "hello", SenderID: "user-1", SenderType: MemberTypeUser}
	require.NoError(t, db.Create(msg).Error)
	assert.True(t, msg.CreateAtMs > 0)
	assert.Equal(t, msg.CreateAtMs, msg.UpdateAtMs)

	time.Sleep(25 * time.Millisecond)
	msg.MessageText = "hello2"
	require.NoError(t, db.Save(msg).Error)
	assert.Greater(t, msg.UpdateAtMs, msg.CreateAtMs)
}

func TestAgentMessageProcessing_Timestamps(t *testing.T) {
	db := newTestDB(t)
	amp := &AgentMessageProcessing{ID: 1, GroupID: "group-1", MessageID: "msg-1", AgentID: "agent-1", Status: ProcessingStatusPending}
	require.NoError(t, db.Create(amp).Error)
	assert.True(t, amp.CreateAtMs > 0)
	assert.Equal(t, amp.CreateAtMs, amp.UpdateAtMs)

	time.Sleep(25 * time.Millisecond)
	amp.Status = ProcessingStatusRunning
	require.NoError(t, db.Save(amp).Error)
	assert.Greater(t, amp.UpdateAtMs, amp.CreateAtMs)
}

// ==================== Status / Role Helpers ====================

func TestAccount_IsActive(t *testing.T) {
	assert.True(t, (&Account{Status: AccountStatusActive}).IsActive())
	assert.False(t, (&Account{Status: AccountStatusInactive}).IsActive())
	assert.False(t, (&Account{Status: AccountStatusDeleted}).IsActive())
}

func TestAccount_IsDeleted(t *testing.T) {
	assert.True(t, (&Account{Status: AccountStatusDeleted}).IsDeleted())
	assert.True(t, (&Account{DeleteAtMs: 1}).IsDeleted())
	assert.False(t, (&Account{Status: AccountStatusActive}).IsDeleted())
	assert.False(t, (&Account{Status: AccountStatusInactive, DeleteAtMs: 0}).IsDeleted())
}

func TestAPIKey_IsActive(t *testing.T) {
	assert.True(t, (&APIKey{Status: APIKeyStatusActive}).IsActive())
	assert.False(t, (&APIKey{Status: APIKeyStatusInactive}).IsActive())
}

func TestGroupMember_IsAgent(t *testing.T) {
	assert.False(t, (&GroupMember{MemberType: MemberTypeUser}).IsAgent())
	assert.True(t, (&GroupMember{MemberType: MemberTypeWorkerAgent}).IsAgent())
	assert.True(t, (&GroupMember{MemberType: MemberTypeManagerAgent}).IsAgent())
}

func TestGroupMessage_IsDeletedFlag(t *testing.T) {
	assert.True(t, (&GroupMessage{IsDeleted: true, DeleteAtMs: 0}).isDeleted())
	assert.True(t, (&GroupMessage{IsDeleted: false, DeleteAtMs: 1}).isDeleted())
	assert.False(t, (&GroupMessage{IsDeleted: false, DeleteAtMs: 0}).isDeleted())
}

func TestAgentMessageProcessing_IsTerminalStatus(t *testing.T) {
	assert.True(t, (&AgentMessageProcessing{Status: ProcessingStatusCompleted}).IsTerminalStatus())
	assert.True(t, (&AgentMessageProcessing{Status: ProcessingStatusFailed}).IsTerminalStatus())
	assert.False(t, (&AgentMessageProcessing{Status: ProcessingStatusPending}).IsTerminalStatus())
	assert.False(t, (&AgentMessageProcessing{Status: ProcessingStatusRunning}).IsTerminalStatus())
	assert.False(t, (&AgentMessageProcessing{Status: "unknown"}).IsTerminalStatus())
}

// ==================== JSON Serialization ====================

func TestGroupMember_MemberInterface_JSON(t *testing.T) {
	iface := map[string]any{
		"adaptor": "topsailai_agent",
		"environments": map[string]string{
			"ACS_AGENT_API_BASE": "http://localhost:7373",
		},
		"timeout_chat": 600,
	}
	data, err := json.Marshal(iface)
	require.NoError(t, err)

	gm := &GroupMember{
		GroupID:         "group-1",
		MemberID:        "agent-1",
		MemberName:      "Agent",
		MemberType:      MemberTypeWorkerAgent,
		MemberInterface: string(data),
	}

	var parsed map[string]any
	require.NoError(t, json.Unmarshal([]byte(gm.MemberInterface), &parsed))
	assert.Equal(t, "topsailai_agent", parsed["adaptor"])
	assert.Equal(t, float64(600), parsed["timeout_chat"])
}

func TestGroupMessage_Mentions_JSON(t *testing.T) {
	mentions := []Mention{
		{MemberID: "agent-1", MemberName: "Agent One", MemberType: "worker-agent"},
	}
	data, err := json.Marshal(mentions)
	require.NoError(t, err)

	msg := &GroupMessage{
		GroupID:     "group-1",
		MessageID:   "msg-1",
		MessageText: "hello",
		SenderID:    "user-1",
		SenderType:  MemberTypeUser,
		Mentions:    string(data),
	}

	var parsed []Mention
	require.NoError(t, json.Unmarshal([]byte(msg.Mentions), &parsed))
	require.Len(t, parsed, 1)
	assert.Equal(t, "agent-1", parsed[0].MemberID)
	assert.Equal(t, "Agent One", parsed[0].MemberName)
}

func TestGroupMessage_Attachments_JSON(t *testing.T) {
	attachments := []Attachment{
		{Data: "base64data", Size: 1024, Format: "image/png"},
	}
	data, err := json.Marshal(attachments)
	require.NoError(t, err)

	msg := &GroupMessage{
		GroupID:            "group-1",
		MessageID:          "msg-1",
		MessageText:        "hello",
		SenderID:           "user-1",
		SenderType:         MemberTypeUser,
		MessageAttachments: string(data),
	}

	var parsed []Attachment
	require.NoError(t, json.Unmarshal([]byte(msg.MessageAttachments), &parsed))
	require.Len(t, parsed, 1)
	assert.Equal(t, "base64data", parsed[0].Data)
	assert.Equal(t, int64(1024), parsed[0].Size)
}

// ==================== Table Names ====================

func TestAccount_TableName(t *testing.T) {
	assert.Equal(t, "accounts", (&Account{}).TableName())
	assert.Equal(t, "accounts", (Account{}).TableName())
}

func TestAPIKey_TableName(t *testing.T) {
	assert.Equal(t, "api_keys", (&APIKey{}).TableName())
}

func TestAuditLog_TableName(t *testing.T) {
	assert.Equal(t, "audit_logs", (&AuditLog{}).TableName())
}

func TestGroup_TableName(t *testing.T) {
	assert.Equal(t, "groups", (&Group{}).TableName())
}

func TestGroupMember_TableName(t *testing.T) {
	assert.Equal(t, "group_member", (&GroupMember{}).TableName())
}

func TestGroupMessage_TableName(t *testing.T) {
	assert.Equal(t, "group_messages", (&GroupMessage{}).TableName())
}

func TestAgentMessageProcessing_TableName(t *testing.T) {
	assert.Equal(t, "agent_message_processing", (&AgentMessageProcessing{}).TableName())
}

// ==================== Role Validation / Hierarchy ====================

func TestAccount_ValidRole(t *testing.T) {
	assert.True(t, (&Account{Role: AccountRoleAdmin}).ValidRole())
	assert.True(t, (&Account{Role: AccountRoleManager}).ValidRole())
	assert.True(t, (&Account{Role: AccountRoleUser}).ValidRole())
	assert.False(t, (&Account{Role: "superuser"}).ValidRole())
	assert.False(t, (&Account{Role: ""}).ValidRole())
}

func TestAccount_RoleRank(t *testing.T) {
	assert.Equal(t, 3, (&Account{Role: AccountRoleAdmin}).RoleRank())
	assert.Equal(t, 2, (&Account{Role: AccountRoleManager}).RoleRank())
	assert.Equal(t, 1, (&Account{Role: AccountRoleUser}).RoleRank())
	assert.Equal(t, 0, (&Account{Role: "unknown"}).RoleRank())
}

func TestAPIKey_RoleAllowedForOwner(t *testing.T) {
	tests := []struct {
		name      string
		keyRole   APIKeyRole
		ownerRole AccountRole
		allowed   bool
	}{
		{"admin key for admin owner", APIKeyRoleAdmin, AccountRoleAdmin, true},
		{"manager key for admin owner", APIKeyRoleManager, AccountRoleAdmin, true},
		{"user key for admin owner", APIKeyRoleUser, AccountRoleAdmin, true},
		{"admin key for manager owner", APIKeyRoleAdmin, AccountRoleManager, false},
		{"manager key for manager owner", APIKeyRoleManager, AccountRoleManager, true},
		{"user key for manager owner", APIKeyRoleUser, AccountRoleManager, true},
		{"admin key for user owner", APIKeyRoleAdmin, AccountRoleUser, false},
		{"manager key for user owner", APIKeyRoleManager, AccountRoleUser, false},
		{"user key for user owner", APIKeyRoleUser, AccountRoleUser, true},
		{"invalid key role", APIKeyRole("invalid"), AccountRoleAdmin, false},
		{"key for invalid owner", APIKeyRoleUser, AccountRole("invalid"), false},
	}
	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			key := &APIKey{Role: tt.keyRole}
			assert.Equal(t, tt.allowed, key.RoleAllowedForOwner(tt.ownerRole))
		})
	}
}

// ==================== Member Type Helpers ====================

func TestGroupMember_IsManagerAgent(t *testing.T) {
	assert.True(t, (&GroupMember{MemberType: MemberTypeManagerAgent}).IsManagerAgent())
	assert.False(t, (&GroupMember{MemberType: MemberTypeWorkerAgent}).IsManagerAgent())
	assert.False(t, (&GroupMember{MemberType: MemberTypeUser}).IsManagerAgent())
}

func TestGroupMember_IsUser(t *testing.T) {
	assert.True(t, (&GroupMember{MemberType: MemberTypeUser}).IsUser())
	assert.False(t, (&GroupMember{MemberType: MemberTypeWorkerAgent}).IsUser())
	assert.False(t, (&GroupMember{MemberType: MemberTypeManagerAgent}).IsUser())
}

// ==================== Message Sender Helpers ====================

func TestGroupMessage_IsFromAgent(t *testing.T) {
	assert.False(t, (&GroupMessage{SenderType: MemberTypeUser}).IsFromAgent())
	assert.True(t, (&GroupMessage{SenderType: MemberTypeWorkerAgent}).IsFromAgent())
	assert.True(t, (&GroupMessage{SenderType: MemberTypeManagerAgent}).IsFromAgent())
}
