// Package main provides command definitions and dispatch for the ACS CLI terminal.
package main

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/chzyer/readline"
)

// Role constants for ACS authorization.
const (
	RoleAdmin   = "admin"
	RoleManager = "manager"
	RoleUser    = "user"
)

// roleRank maps roles to numeric rank for comparison.
var roleRank = map[string]int{
	RoleAdmin:   3,
	RoleManager: 2,
	RoleUser:    1,
}
// CLIState holds the runtime state of the CLI.
type CLIState struct {
	apiClient   *APIClient
	natsManager *NATSManager
	chatMode    *ChatMode
	userID      string
	userName    string
	accountRole string
	authMethod  AuthMethod
	apiKey      string
	sessionKey  string
	expiresAtMs int64
	lastGroupID string
	running     bool
	rl          *readline.Instance
}

// sanitizeMemberName removes characters that are not allowed in ACS member names.
// Allowed characters are alphanumeric, hyphens, and underscores.
func sanitizeMemberName(name string) string {
	var sb strings.Builder
	for _, r := range name {
		switch {
		case r >= 'a' && r <= 'z', r >= 'A' && r <= 'Z', r >= '0' && r <= '9', r == '-', r == '_':
			sb.WriteRune(r)
		default:
			sb.WriteRune('_')
		}
	}
	return sb.String()
}

// CommandHandler is a function that handles a CLI command.
type CommandHandler func(args []string, state *CLIState) error
var commandHandlers = map[string]CommandHandler{
	"/login":            handleLogin,
	"/logout":           handleLogout,
	"/account:me":       handleAccountMe,
	"/account:create":   handleAccountCreate,
	"/account:list":     handleAccountList,
	"/account:get":      handleAccountGet,
	"/account:update":   handleAccountUpdate,
	"/account:delete":   handleAccountDelete,
	"/account:password": handleAccountPassword,
	"/account:session":  handleAccountSession,
	"/api-key:create":   handleAPIKeyCreate,
	"/api-key:list":     handleAPIKeyList,
	"/api-key:delete":   handleAPIKeyDelete,
	"/group:list":       handleGroupList,
	"/group:create":     handleGroupCreate,
	"/group:enter":      handleGroupEnter,
	"/group:join":       handleGroupJoin,
	"/group:update":     handleGroupUpdate,
	"/group:delete":     handleGroupDelete,
	"/member:list":      handleMemberList,
	"/member:add":       handleMemberAdd,
	"/member:remove":    handleMemberRemove,
	"/member:update":    handleMemberUpdate,
	"/message:list":     handleMessageList,
	"/message:edit":     handleMessageEdit,
	"/message:delete":   handleMessageDelete,
	"/help":             handleHelp,
	"/exit":             handleExit,
}

var commandAliases = map[string]string{
	"exit": "/exit",
	"quit": "/exit",
	"help": "/help",
}

// DispatchCommand parses and dispatches a command line.
func DispatchCommand(line string, state *CLIState) error {
	line = strings.TrimSpace(line)
	if line == "" {
		return nil
	}

	// Resolve aliases.
	lower := strings.ToLower(line)
	if alias, ok := commandAliases[lower]; ok {
		line = alias
	}

	parts := strings.Fields(line)
	if len(parts) == 0 {
		return nil
	}

	cmd := parts[0]
	args := parts[1:]

	handler, ok := commandHandlers[cmd]
	if !ok {
		return fmt.Errorf("unknown command: %s", cmd)
	}

	return handler(args, state)
}

// parseInlineArgs parses inline arguments into a map.
// Supports --key value and key=value formats.
func parseInlineArgs(args []string) map[string]string {
	result := make(map[string]string)
	for i := 0; i < len(args); i++ {
		arg := args[i]
		if strings.HasPrefix(arg, "--") {
			key := strings.TrimPrefix(arg, "--")
			if i+1 < len(args) && !strings.HasPrefix(args[i+1], "--") {
				result[key] = args[i+1]
				i++
			} else {
				result[key] = "true"
			}
		} else if strings.Contains(arg, "=") {
			parts := strings.SplitN(arg, "=", 2)
			result[parts[0]] = parts[1]
		}
	}
	return result
}

// requireAuth returns an error if the CLI is not authenticated.
func requireAuth(state *CLIState) error {
	if !state.apiClient.IsAuthenticated() {
		return fmt.Errorf("authentication required. Use /login or start with --api-key/--session-key")
	}
	return nil
}

// requireRole returns an error if the caller's role is below the required role.
func requireRole(state *CLIState, required string) error {
	if err := requireAuth(state); err != nil {
		return err
	}
	if !hasRole(state.accountRole, required) {
		return fmt.Errorf("access denied: role '%s' required, current role is '%s'", required, state.accountRole)
	}
	return nil
}

// hasRole returns true when role meets or exceeds the required role.
func hasRole(role, required string) bool {
	return roleRank[role] >= roleRank[required]
}

// updateAuthState refreshes CLIState after a successful login or session creation.
func updateAuthState(state *CLIState, method AuthMethod, credential, accountID, accountName, role string, expiresAtMs int64) {
	state.authMethod = method
	state.apiClient.SetAuthMethod(method, credential)
	if method == AuthMethodAPIKey {
		state.apiKey = credential
		state.sessionKey = ""
	} else {
		state.sessionKey = credential
		state.apiKey = ""
	}
	state.userID = accountID
	state.userName = accountName
	state.accountRole = role
	state.expiresAtMs = expiresAtMs
	if state.rl != nil {
		state.rl.SetPrompt(ps1Normal(accountName, state.userID, role))
	}
}

// clearAuthState resets authentication-related state to anonymous.
func clearAuthState(state *CLIState) {
	state.authMethod = ""
	state.apiKey = ""
	state.sessionKey = ""
	state.accountRole = ""
	state.expiresAtMs = 0
	state.userID = ""
	state.userName = "anonymous"
	state.apiClient.SetAuthMethod("", "")
	if state.rl != nil {
		state.rl.SetPrompt(ps1Normal("anonymous", "", ""))
	}
}

// formatAPIError converts a raw HTTP error into a user-friendly message.
func formatAPIError(err error) error {
	msg := err.Error()
	if strings.Contains(msg, "HTTP 401") {
		return fmt.Errorf("authentication required. Use /login or start with --api-key/--session-key (trace: %s)", msg)
	}
	if strings.Contains(msg, "HTTP 403") {
		return fmt.Errorf("access denied. Your role does not have permission. (trace: %s)", msg)
	}
	return err
}

// restorePrompt resets the readline prompt to normal mode.
func restorePrompt(state *CLIState) {
	if state.rl == nil {
		return
	}
	state.rl.SetPrompt(ps1Normal(state.userName, state.userID, state.accountRole))
}

// --- Authentication commands ---

func handleLogin(args []string, state *CLIState) error {
	defer restorePrompt(state)
	params := parseInlineArgs(args)

	loginName := params["login-name"]
	loginPassword := params["login-password"]

	if loginName == "" || loginPassword == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		loginName, loginPassword, err = PromptLogin(prompt)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	resp, err := state.apiClient.Login(loginName, loginPassword)
	if err != nil {
		return formatAPIError(err)
	}

	var result struct {
		AccountID   string `json:"account_id"`
		SessionKey  string `json:"session_key"`
		ExpiresAtMs int64  `json:"expires_at_ms"`
	}
	if err := resp.GetData(&result); err != nil {
		return err
	}

	// The server login response only contains account_id, session_key and
	// expires_at_ms. Fetch /account:me to obtain the account name and role so
	// the prompt and success message are populated correctly.
	updateAuthState(state, AuthMethodSession, result.SessionKey, result.AccountID, "", "", result.ExpiresAtMs)

	meResp, err := state.apiClient.GetMe()
	if err != nil {
		return formatAPIError(err)
	}
	var me map[string]interface{}
	if err := meResp.GetData(&me); err != nil {
		return err
	}
	accountName, _ := me["account_name"].(string)
	role, _ := me["role"].(string)
	updateAuthState(state, AuthMethodSession, result.SessionKey, result.AccountID, accountName, role, result.ExpiresAtMs)

	printSuccess(fmt.Sprintf("Logged in as %s [%s]", accountName, role))
	promptPrintln(fmt.Sprintf("Session key: %s", result.SessionKey))
	return nil
}

func handleLogout(args []string, state *CLIState) error {
	clearAuthState(state)
	printInfo("Logged out.")
	return nil
}

// --- Account commands ---

func handleAccountMe(args []string, state *CLIState) error {
	defer restorePrompt(state)
	if err := requireAuth(state); err != nil {
		return err
	}

	resp, err := state.apiClient.GetMe()
	if err != nil {
		return formatAPIError(err)
	}

	var account map[string]interface{}
	if err := resp.GetData(&account); err != nil {
		return err
	}

	role, _ := account["role"].(string)
	name, _ := account["account_name"].(string)
	id, _ := account["account_id"].(string)
	state.accountRole = role
	state.userName = name
	state.userID = id
	if state.rl != nil {
		state.rl.SetPrompt(ps1Normal(name, id, role))
	}

	promptPrintln(formatAccountDetail(account))
	return nil
}

func handleAccountCreate(args []string, state *CLIState) error {
	defer restorePrompt(state)
	if err := requireRole(state, RoleManager); err != nil {
		return err
	}

	params := parseInlineArgs(args)
	req := buildAccountCreateRequest(params)

	if req["account_name"] == nil {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		req, err = PromptAccountCreate(prompt, state.accountRole)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	// Managers can only create user accounts.
	if state.accountRole == RoleManager {
		req["role"] = RoleUser
	}

	resp, err := state.apiClient.CreateAccount(req)
	if err != nil {
		return formatAPIError(err)
	}

	var account map[string]interface{}
	if err := resp.GetData(&account); err != nil {
		return err
	}
	printSuccess(fmt.Sprintf("Account created: %s", account["account_id"]))
	return nil
}

func handleAccountList(args []string, state *CLIState) error {
	defer restorePrompt(state)
	if err := requireRole(state, RoleManager); err != nil {
		return err
	}

	params := parseInlineArgs(args)
	q := ListQuery{Limit: 100}
	if offset, err := strconv.Atoi(params["offset"]); err == nil {
		q.Offset = offset
	}
	if limit, err := strconv.Atoi(params["limit"]); err == nil {
		q.Limit = limit
	}
	q.SortKey = params["sort-key"]
	q.OrderBy = params["order-by"]

	resp, err := state.apiClient.ListAccounts(q, params["role"], params["status"], params["external-id"])
	if err != nil {
		return formatAPIError(err)
	}

	var result struct {
		Items []map[string]interface{} `json:"items"`
		Total int                      `json:"total"`
	}
	if err := resp.GetData(&result); err != nil {
		return err
	}

	if len(result.Items) == 0 {
		printInfo("No accounts found.")
		return nil
	}

	printSeparator()
	promptPrintf("Accounts (total: %d):\n", result.Total)
	for _, a := range result.Items {
		promptPrintln(formatAccountLine(a))
	}
	printSeparator()
	return nil
}

func handleAccountGet(args []string, state *CLIState) error {
	defer restorePrompt(state)
	if err := requireAuth(state); err != nil {
		return err
	}

	params := parseInlineArgs(args)
	accountID := params["id"]
	if accountID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		accountID, err = prompt.PromptString("Account ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	// Users can only access their own account.
	if state.accountRole == RoleUser && accountID != state.userID {
		return fmt.Errorf("access denied: you can only view your own account")
	}

	resp, err := state.apiClient.GetAccount(accountID)
	if err != nil {
		return formatAPIError(err)
	}

	var account map[string]interface{}
	if err := resp.GetData(&account); err != nil {
		return err
	}
	promptPrintln(formatAccountDetail(account))
	return nil
}

func handleAccountUpdate(args []string, state *CLIState) error {
	defer restorePrompt(state)
	if err := requireAuth(state); err != nil {
		return err
	}

	params := parseInlineArgs(args)
	accountID := params["id"]
	if accountID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		accountID, err = prompt.PromptString("Account ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	// Users can only update their own account and cannot change role/status.
	if state.accountRole == RoleUser && accountID != state.userID {
		return fmt.Errorf("access denied: you can only update your own account")
	}

	req := buildAccountUpdateRequest(params)
	if len(req) == 0 {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		req, err = PromptAccountUpdate(prompt)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	// Non-admin users cannot change role or status.
	if state.accountRole != RoleAdmin {
		delete(req, "role")
		delete(req, "status")
	}

	_, err := state.apiClient.UpdateAccount(accountID, req)
	if err != nil {
		return formatAPIError(err)
	}

	printSuccess(fmt.Sprintf("Account %s updated", accountID))
	return nil
}

func handleAccountDelete(args []string, state *CLIState) error {
	defer restorePrompt(state)
	if err := requireRole(state, RoleAdmin); err != nil {
		return err
	}

	params := parseInlineArgs(args)
	accountID := params["id"]
	if accountID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		accountID, err = prompt.PromptString("Account ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	prompt := NewInteractivePrompt(state.rl)
	confirm, err := prompt.PromptBool(fmt.Sprintf("Delete account %s?", accountID), false)
	if err != nil {
		if err == ErrCancelled {
			printInfo("Cancelled.")
			return nil
		}
		return err
	}
	if !confirm {
		printInfo("Deletion cancelled.")
		return nil
	}

	_, err = state.apiClient.DeleteAccount(accountID)
	if err != nil {
		return formatAPIError(err)
	}

	printSuccess(fmt.Sprintf("Account %s deleted", accountID))
	return nil
}

func handleAccountPassword(args []string, state *CLIState) error {
	defer restorePrompt(state)
	if err := requireAuth(state); err != nil {
		return err
	}

	params := parseInlineArgs(args)
	accountID := params["id"]
	if accountID == "" {
		// Default to the current account for self-service password changes.
		// Admins can target another account via --id.
		accountID = state.userID
	}

	// Users can only change their own password.
	if state.accountRole == RoleUser && accountID != state.userID {
		return fmt.Errorf("access denied: you can only change your own password")
	}

	oldPassword := params["old-password"]
	newPassword := params["new-password"]

	if newPassword == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		oldPassword, newPassword, err = PromptPasswordChange(prompt, state.accountRole != RoleAdmin)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	_, err := state.apiClient.ChangePassword(accountID, oldPassword, newPassword)
	if err != nil {
		return formatAPIError(err)
	}

	printSuccess("Password updated")
	return nil
}

func handleAccountSession(args []string, state *CLIState) error {
	defer restorePrompt(state)
	if err := requireRole(state, RoleManager); err != nil {
		return err
	}

	params := parseInlineArgs(args)
	accountID := params["id"]
	if accountID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		accountID, err = prompt.PromptString("Account ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	resp, err := state.apiClient.CreateSession(accountID)
	if err != nil {
		return formatAPIError(err)
	}

	var result map[string]interface{}
	if err := resp.GetData(&result); err != nil {
		return err
	}
	promptPrintln(formatSessionInfo(result))
	return nil
}

// --- API key commands ---

func handleAPIKeyCreate(args []string, state *CLIState) error {
	defer restorePrompt(state)
	if err := requireAuth(state); err != nil {
		return err
	}

	params := parseInlineArgs(args)
	accountID := params["account-id"]
	name := params["name"]
	role := params["role"]

	if accountID == "" || name == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		accountID, name, role, err = PromptAPIKeyCreate(prompt, state.accountRole, state.userID)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	// Users can only create keys for themselves.
	if state.accountRole == RoleUser && accountID != state.userID {
		return fmt.Errorf("access denied: you can only create API keys for your own account")
	}
	// Users cannot create keys with a role higher than user.
	if state.accountRole == RoleUser && role != "" && role != RoleUser {
		return fmt.Errorf("access denied: you can only create user-level API keys")
	}

	resp, err := state.apiClient.CreateAPIKey(accountID, name, role)
	if err != nil {
		return formatAPIError(err)
	}

	var result map[string]interface{}
	if err := resp.GetData(&result); err != nil {
		return err
	}
	printSuccess("API key created")
	promptPrintln(formatAPIKeyDetail(result))
	printWarning("Save the token now. It will not be shown again.")
	return nil
}

func handleAPIKeyList(args []string, state *CLIState) error {
	defer restorePrompt(state)
	if err := requireAuth(state); err != nil {
		return err
	}

	params := parseInlineArgs(args)
	accountID := params["account-id"]
	status := params["status"]
	if accountID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		accountID, status, err = PromptAPIKeyList(prompt, state.userID)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	// Users can only list keys for themselves.
	if state.accountRole == RoleUser && accountID != state.userID {
		return fmt.Errorf("access denied: you can only list your own API keys")
	}

	q := ListQuery{Limit: 100}
	if offset, err := strconv.Atoi(params["offset"]); err == nil {
		q.Offset = offset
	}
	if limit, err := strconv.Atoi(params["limit"]); err == nil {
		q.Limit = limit
	}

	resp, err := state.apiClient.ListAPIKeys(accountID, q, status)
	if err != nil {
		return formatAPIError(err)
	}
	var result struct {
		Items []map[string]interface{} `json:"items"`
		Total int                      `json:"total"`
	}
	if err := resp.GetData(&result); err != nil {
		return err
	}

	if len(result.Items) == 0 {
		printInfo("No API keys found.")
		return nil
	}

	printSeparator()
	promptPrintf("API keys (total: %d):\n", result.Total)
	for _, k := range result.Items {
		promptPrintln(formatAPIKeyLine(k))
	}
	printSeparator()
	return nil
}

func handleAPIKeyDelete(args []string, state *CLIState) error {
	defer restorePrompt(state)
	if err := requireAuth(state); err != nil {
		return err
	}

	params := parseInlineArgs(args)
	accountID := params["account-id"]
	apiKeyID := params["key-id"]

	if accountID == "" || apiKeyID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		accountID, apiKeyID, err = PromptAPIKeyDelete(prompt, state.userID)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	// Users can only delete keys for themselves.
	if state.accountRole == RoleUser && accountID != state.userID {
		return fmt.Errorf("access denied: you can only delete your own API keys")
	}

	_, err := state.apiClient.DeleteAPIKey(accountID, apiKeyID)
	if err != nil {
		return formatAPIError(err)
	}

	printSuccess(fmt.Sprintf("API key %s deleted", apiKeyID))
	return nil
}

// --- Group commands ---

func handleGroupList(args []string, state *CLIState) error {
	defer restorePrompt(state)
	params := parseInlineArgs(args)

	q := ListQuery{Limit: 100}
	if offset, err := strconv.Atoi(params["offset"]); err == nil {
		q.Offset = offset
	}
	if limit, err := strconv.Atoi(params["limit"]); err == nil {
		q.Limit = limit
	}
	q.SortKey = params["sort-key"]
	q.OrderBy = params["order-by"]
	q.CreateAtMs = params["create-at-ms"]
	q.UpdateAtMs = params["update-at-ms"]

	resp, err := state.apiClient.ListGroups(q)
	if err != nil {
		return formatAPIError(err)
	}

	var result struct {
		Items []map[string]interface{} `json:"items"`
		Total int                      `json:"total"`
	}
	if err := resp.GetData(&result); err != nil {
		return err
	}

	if len(result.Items) == 0 {
		printInfo("No groups found.")
		return nil
	}

	printSeparator()
	promptPrintf("Groups (total: %d):\n", result.Total)
	for _, g := range result.Items {
		id, _ := g["group_id"].(string)
		name, _ := g["group_name"].(string)
		promptPrintln(formatGroupLine(id, name))
	}
	printSeparator()
	return nil
}

func handleGroupCreate(args []string, state *CLIState) error {
	defer restorePrompt(state)
	params := parseInlineArgs(args)

	name := params["name"]
	context := params["context"]
	key := params["key"]

	if name == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		name, context, key, err = PromptGroupCreate(prompt)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	resp, err := state.apiClient.CreateGroup(name, context, key)
	if err != nil {
		return formatAPIError(err)
	}

	var group map[string]interface{}
	if err := resp.GetData(&group); err != nil {
		return err
	}

	id, _ := group["group_id"].(string)
	printSuccess(fmt.Sprintf("Group created: %s", id))
	return nil
}

func handleGroupEnter(args []string, state *CLIState) error {
	params := parseInlineArgs(args)
	groupID := params["group-id"]

	// Support direct inline argument: /group:enter <group_id>
	if groupID == "" && len(args) > 0 {
		groupID = strings.TrimSpace(args[0])
	}

	if groupID == "" {
		defer restorePrompt(state)
		prompt := NewInteractivePrompt(state.rl)
		var err error
		groupID, err = prompt.PromptString("Group ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	// Validate group exists before closing main readline.
	if _, err := state.apiClient.GetGroup(groupID); err != nil {
		return fmt.Errorf("failed to enter group: %w", err)
	}
	// Resolve the group member ID for the current user. The user must already
	// be a member of the group; auto-join is not allowed.
	if err := resolveMember(state, groupID); err != nil {
		return fmt.Errorf("failed to enter group: %w", err)
	}

	// Remember the last active group for contextual commands.
	state.lastGroupID = groupID

	// Close main readline to release terminal for chat mode.
	state.rl.Close()

	chatErr := state.chatMode.EnterChat(groupID, state.userID, state.userName)

	// Recreate main readline after chat mode exits.
	rl, rerr := readline.NewEx(&readline.Config{
		Prompt:       ps1Normal(state.userName, state.userID, state.accountRole),
		AutoComplete: newNormalCompleter(),
	})
	if rerr != nil {
		state.running = false
		return fmt.Errorf("failed to recreate readline: %w", rerr)
	}
	state.rl = rl

	return chatErr
}

// resolveMember checks whether the current user is already a member of the
// group. If the user is not a member, it returns an error and does NOT auto-join.
func resolveMember(state *CLIState, groupID string) error {
	resp, err := state.apiClient.ListMembers(groupID, ListQuery{Limit: 1000})
	if err != nil {
		return err
	}

	var result struct {
		Items []map[string]interface{} `json:"items"`
	}
	if err := resp.GetData(&result); err != nil {
		return err
	}

	// Verify the authenticated account is a member of the group.
	for _, m := range result.Items {
		id, _ := m["member_id"].(string)
		mtype, _ := m["member_type"].(string)
		if id == state.userID && mtype == "user" {
			return nil
		}
	}

	return fmt.Errorf("you are not a member of group %s; use /group:join or ask an admin to add you", groupID)
}

func handleGroupJoin(args []string, state *CLIState) error {
	defer restorePrompt(state)
	if err := requireAuth(state); err != nil {
		return err
	}

	params := parseInlineArgs(args)
	groupID := params["group-id"]
	groupKey := params["group-key"]

	if groupID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		groupID, err = prompt.PromptString("Group ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	// Verify group exists and check whether a key is required.
	resp, err := state.apiClient.GetGroup(groupID)
	if err != nil {
		return formatAPIError(err)
	}

	var group map[string]interface{}
	if err := resp.GetData(&group); err != nil {
		return err
	}

	// If the group has a non-empty group_key hash, prompt for the plaintext key.
	if keyHash, _ := group["group_key"].(string); keyHash != "" && groupKey == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		groupKey, err = prompt.PromptString("Group key (required)", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	// Join the group as a user member.
	memberName := sanitizeMemberName(state.userName)
	if memberName == "" {
		memberName = state.userID
	}
	_, err = state.apiClient.AddMember(groupID, state.userID, memberName, "", "user", nil)
	if err != nil {
		return formatAPIError(err)
	}

	// Remember the last active group.
	state.lastGroupID = groupID

	printSuccess(fmt.Sprintf("Joined group %s as %s", groupID, memberName))
	return nil
}

func handleGroupUpdate(args []string, state *CLIState) error {
	defer restorePrompt(state)
	params := parseInlineArgs(args)
	groupID := params["group-id"]
	if groupID == "" {
		groupID = state.lastGroupID
	}

	if groupID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		groupID, err = prompt.PromptString("Group ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}
	name := params["name"]
	context := params["context"]
	key := params["key"]

	if name == "" && context == "" && key == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		name, context, key, err = PromptGroupUpdate(prompt)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}
	_, err := state.apiClient.UpdateGroup(groupID, name, context, key)
	if err != nil {
		return formatAPIError(err)
	}

	printSuccess(fmt.Sprintf("Group %s updated", groupID))
	return nil
}

func handleGroupDelete(args []string, state *CLIState) error {
	defer restorePrompt(state)
	params := parseInlineArgs(args)
	groupID := params["group-id"]
	if groupID == "" {
		groupID = state.lastGroupID
	}

	if groupID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		groupID, err = prompt.PromptString("Group ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	prompt := NewInteractivePrompt(state.rl)
	confirm, err := prompt.PromptBool(fmt.Sprintf("Delete group %s?", groupID), false)
	if err != nil {
		if err == ErrCancelled {
			printInfo("Cancelled.")
			return nil
		}
		return err
	}
	if !confirm {
		printInfo("Deletion cancelled.")
		return nil
	}

	_, err = state.apiClient.DeleteGroup(groupID)
	if err != nil {
		return formatAPIError(err)
	}

	if state.lastGroupID == groupID {
		state.lastGroupID = ""
	}
	printSuccess(fmt.Sprintf("Group %s deleted", groupID))
	return nil
}

// --- Member commands ---

func handleMemberList(args []string, state *CLIState) error {
	defer restorePrompt(state)
	params := parseInlineArgs(args)
	groupID := params["group-id"]
	if groupID == "" {
		groupID = state.lastGroupID
	}

	if groupID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		groupID, err = prompt.PromptString("Group ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	q := ListQuery{Limit: 1000}
	resp, err := state.apiClient.ListMembers(groupID, q)
	if err != nil {
		return formatAPIError(err)
	}

	var result struct {
		Items []map[string]interface{} `json:"items"`
	}
	if err := resp.GetData(&result); err != nil {
		return err
	}

	if len(result.Items) == 0 {
		printInfo("No members found.")
		return nil
	}

	printSeparator()
	promptPrintln("Members:")
	for _, m := range result.Items {
		id, _ := m["member_id"].(string)
		name, _ := m["member_name"].(string)
		mtype, _ := m["member_type"].(string)
		status, _ := m["member_status"].(string)
		promptPrintln(formatMemberLine(mtype, name, id, status))
	}
	printSeparator()
	return nil
}

func handleMemberAdd(args []string, state *CLIState) error {
	defer restorePrompt(state)
	params := parseInlineArgs(args)
	groupID := params["group-id"]
	if groupID == "" {
		groupID = state.lastGroupID
	}
	memberID := params["member-id"]
	memberName := params["member-name"]
	memberDesc := params["member-description"]
	memberType := params["member-type"]

	if groupID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		groupID, err = prompt.PromptString("Group ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	if memberID == "" || memberName == "" || memberType == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		memberID, memberName, memberDesc, memberType, _, err = PromptMemberAdd(prompt)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	_, err := state.apiClient.AddMember(groupID, memberID, memberName, memberDesc, memberType, nil)
	if err != nil {
		return formatAPIError(err)
	}

	printSuccess(fmt.Sprintf("Member %s added to group %s", memberID, groupID))
	return nil
}

func handleMemberRemove(args []string, state *CLIState) error {
	defer restorePrompt(state)
	params := parseInlineArgs(args)
	groupID := params["group-id"]
	memberID := params["member-id"]

	if groupID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		groupID, err = prompt.PromptString("Group ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	if memberID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		memberID, err = prompt.PromptString("Member ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	_, err := state.apiClient.RemoveMember(groupID, memberID)
	if err != nil {
		return formatAPIError(err)
	}

	printSuccess(fmt.Sprintf("Member %s removed from group %s", memberID, groupID))
	return nil
}

func handleMemberUpdate(args []string, state *CLIState) error {
	defer restorePrompt(state)
	params := parseInlineArgs(args)
	groupID := params["group-id"]
	memberID := params["member-id"]

	if groupID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		groupID, err = prompt.PromptString("Group ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	if memberID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		memberID, err = prompt.PromptString("Member ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	memberName := params["member-name"]
	memberDesc := params["member-description"]
	memberStatus := params["member-status"]

	if memberName == "" && memberDesc == "" && memberStatus == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		memberName, memberDesc, memberStatus, err = PromptMemberUpdate(prompt)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	_, err := state.apiClient.UpdateMember(groupID, memberID, memberName, memberDesc, memberStatus, nil)
	if err != nil {
		return formatAPIError(err)
	}

	printSuccess(fmt.Sprintf("Member %s updated", memberID))
	return nil
}

// --- Message commands ---

func handleMessageList(args []string, state *CLIState) error {
	defer restorePrompt(state)
	params := parseInlineArgs(args)
	groupID := params["group-id"]

	if groupID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		groupID, err = prompt.PromptString("Group ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	q := ListQuery{
		Limit:   50,
		OrderBy: "asc",
		SortKey: "create_at_ms",
	}
	if limit, err := strconv.Atoi(params["limit"]); err == nil {
		q.Limit = limit
	}

	resp, err := state.apiClient.ListMessages(groupID, q)
	if err != nil {
		return formatAPIError(err)
	}

	var result struct {
		Items []map[string]interface{} `json:"items"`
	}
	if err := resp.GetData(&result); err != nil {
		return err
	}

	if len(result.Items) == 0 {
		printInfo("No messages found.")
		return nil
	}

	printDoubleSeparator()
	promptPrintf("Messages for group %s:\n", groupID)
	for _, msg := range result.Items {
		promptPrintln(formatMessage(msg))
	}
	printDoubleSeparator()
	return nil
}

func handleMessageEdit(args []string, state *CLIState) error {
	defer restorePrompt(state)
	params := parseInlineArgs(args)
	groupID := params["group-id"]
	messageID := params["message-id"]

	if groupID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		groupID, err = prompt.PromptString("Group ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	if messageID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		messageID, err = prompt.PromptString("Message ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	text := params["text"]
	if text == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		text, err = PromptMessageEdit(prompt)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	_, err := state.apiClient.UpdateMessage(groupID, messageID, text)
	if err != nil {
		return formatAPIError(err)
	}

	printSuccess("Message updated")
	return nil
}

func handleMessageDelete(args []string, state *CLIState) error {
	defer restorePrompt(state)
	params := parseInlineArgs(args)
	groupID := params["group-id"]
	messageID := params["message-id"]

	if groupID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		groupID, err = prompt.PromptString("Group ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	if messageID == "" {
		prompt := NewInteractivePrompt(state.rl)
		var err error
		messageID, err = prompt.PromptString("Message ID", true)
		if err != nil {
			if err == ErrCancelled {
				printInfo("Cancelled.")
				return nil
			}
			return err
		}
	}

	_, err := state.apiClient.DeleteMessage(groupID, messageID)
	if err != nil {
		return formatAPIError(err)
	}

	printSuccess("Message deleted")
	return nil
}

// --- Other commands ---

func handleHelp(args []string, state *CLIState) error {
	promptPrintln(yellow("Available commands:"))
	printSeparator()
	promptPrintln("Authentication:")
	promptPrintln("  /login           Login with login_name and password")
	promptPrintln("  /logout          Clear current credentials")
	promptPrintln()
	promptPrintln("Account commands:")
	promptPrintln("  /account:me      Show current account")
	promptPrintln("  /account:create  Create a new account (admin/manager)")
	promptPrintln("  /account:list    List accounts (admin/manager)")
	promptPrintln("  /account:get     Get account details")
	promptPrintln("  /account:update  Update an account")
	promptPrintln("  /account:delete  Delete an account (admin)")
	promptPrintln("  /account:password Change account password")
	promptPrintln("  /account:session Create a login session (admin/manager)")
	promptPrintln()
	promptPrintln("API key commands:")
	promptPrintln("  /api-key:create  Create an API key")
	promptPrintln("  /api-key:list    List API keys")
	promptPrintln("  /api-key:delete  Delete an API key")
	promptPrintln()
	promptPrintln("Group commands:")
	promptPrintln("  /group:list     List groups you have joined")
	promptPrintln("  /group:create   Create a new group")
	promptPrintln("  /group:enter    Enter a group you have joined")
	promptPrintln("  /group:update   Update a group")
	promptPrintln("  /group:delete   Delete a group")
	promptPrintln()
	promptPrintln("Member commands:")
	promptPrintln("  /member:list    List group members")
	promptPrintln("  /member:add     Add a member to a group")
	promptPrintln("  /member:remove  Remove a member from a group")
	promptPrintln("  /member:update  Update a member")
	promptPrintln()
	promptPrintln("Message commands:")
	promptPrintln("  /message:list   List messages in a group")
	promptPrintln("  /message:edit   Edit a message")
	promptPrintln("  /message:delete Delete a message")
	promptPrintln()
	promptPrintln("Other commands:")
	promptPrintln("  /help           Show this help")
	promptPrintln("  /exit           Exit the CLI")
	promptPrintln("  exit, quit      Aliases for /exit")
	printSeparator()
	promptPrintln("Interactive mode: type a command without arguments to be prompted.")
	promptPrintln("Non-interactive mode: /command --arg value")
	return nil
}

func handleExit(args []string, state *CLIState) error {
	state.running = false
	return nil
}

// buildAccountCreateRequest builds a create-account request from inline args.
func buildAccountCreateRequest(params map[string]string) map[string]interface{} {
	req := map[string]interface{}{}
	if v := params["name"]; v != "" {
		req["account_name"] = v
	}
	if v := params["description"]; v != "" {
		req["account_description"] = v
	}
	if v := params["role"]; v != "" {
		req["role"] = v
	}
	if v := params["login-name"]; v != "" {
		req["login_name"] = v
	}
	if v := params["login-password"]; v != "" {
		req["login_password"] = v
	}
	if v := params["external-id"]; v != "" {
		req["external_id"] = v
	}
	if v := params["email"]; v != "" {
		req["email"] = v
	}
	if v := params["auth-provider"]; v != "" {
		req["auth_provider"] = v
	}
	if v := params["avatar-url"]; v != "" {
		req["avatar_url"] = v
	}
	return req
}

// buildAccountUpdateRequest builds an update-account request from inline args.
func buildAccountUpdateRequest(params map[string]string) map[string]interface{} {
	req := map[string]interface{}{}
	if v := params["name"]; v != "" {
		req["account_name"] = v
	}
	if v := params["description"]; v != "" {
		req["account_description"] = v
	}
	if v := params["role"]; v != "" {
		req["role"] = v
	}
	if v := params["status"]; v != "" {
		req["status"] = v
	}
	if v := params["avatar-url"]; v != "" {
		req["avatar_url"] = v
	}
	return req
}
