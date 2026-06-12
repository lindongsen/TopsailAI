// Package main provides command definitions and dispatch for the ACS CLI terminal.
package main

import (
	"fmt"
	"strconv"
	"strings"

	"github.com/chzyer/readline"
)

// CLIState holds the runtime state of the CLI.
type CLIState struct {
	apiClient   *APIClient
	natsManager *NATSManager
	chatMode    *ChatMode
	userID      string
	userName    string
	running     bool
	rl          *readline.Instance
}

// CommandHandler is a function that handles a CLI command.
type CommandHandler func(args []string, state *CLIState) error

var commandHandlers = map[string]CommandHandler{
	"/group:list":     handleGroupList,
	"/group:create":   handleGroupCreate,
	"/group:enter":    handleGroupEnter,
	"/group:update":   handleGroupUpdate,
	"/group:delete":   handleGroupDelete,
	"/member:list":    handleMemberList,
	"/member:add":     handleMemberAdd,
	"/member:remove":  handleMemberRemove,
	"/member:update":  handleMemberUpdate,
	"/message:list":   handleMessageList,
	"/message:edit":   handleMessageEdit,
	"/message:delete": handleMessageDelete,
	"/help":           handleHelp,
	"/exit":           handleExit,
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

// restorePrompt resets the readline prompt to normal mode.
func restorePrompt(state *CLIState) {
	if state.rl == nil {
		return
	}
	state.rl.SetPrompt(ps1Normal(state.userName))
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
		return err
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
	fmt.Printf("Groups (total: %d):\n", result.Total)
	for _, g := range result.Items {
		id, _ := g["group_id"].(string)
		name, _ := g["group_name"].(string)
		fmt.Println(formatGroupLine(id, name))
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
		prompt := &InteractivePrompt{rl: state.rl}
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
		return err
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

	if groupID == "" {
		defer restorePrompt(state)
		prompt := &InteractivePrompt{rl: state.rl}
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

	// Close main readline to release terminal for chat mode.
	state.rl.Close()

	err := state.chatMode.EnterChat(groupID, state.userID, state.userName)

	// Recreate main readline after chat mode exits.
	rl, rerr := readline.New(ps1Normal(state.userName))
	if rerr != nil {
		state.running = false
		return fmt.Errorf("failed to recreate readline: %w", rerr)
	}
	state.rl = rl

	return err
}

func handleGroupUpdate(args []string, state *CLIState) error {
	defer restorePrompt(state)
	params := parseInlineArgs(args)
	groupID := params["group-id"]

	if groupID == "" {
		prompt := &InteractivePrompt{rl: state.rl}
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
		prompt := &InteractivePrompt{rl: state.rl}
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
		return err
	}

	printSuccess(fmt.Sprintf("Group %s updated", groupID))
	return nil
}

func handleGroupDelete(args []string, state *CLIState) error {
	defer restorePrompt(state)
	params := parseInlineArgs(args)
	groupID := params["group-id"]

	if groupID == "" {
		prompt := &InteractivePrompt{rl: state.rl}
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

	prompt := &InteractivePrompt{rl: state.rl}
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
		return err
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
		prompt := &InteractivePrompt{rl: state.rl}
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
		return err
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
	fmt.Println("Members:")
	for _, m := range result.Items {
		id, _ := m["member_id"].(string)
		name, _ := m["member_name"].(string)
		mtype, _ := m["member_type"].(string)
		status, _ := m["member_status"].(string)
		fmt.Println(formatMemberLine(mtype, name, id, status))
	}
	printSeparator()
	return nil
}

func handleMemberAdd(args []string, state *CLIState) error {
	defer restorePrompt(state)
	params := parseInlineArgs(args)
	groupID := params["group-id"]
	memberID := params["member-id"]
	memberName := params["member-name"]
	memberDesc := params["member-description"]
	memberType := params["member-type"]

	if groupID == "" {
		prompt := &InteractivePrompt{rl: state.rl}
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
		prompt := &InteractivePrompt{rl: state.rl}
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
		return err
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
		prompt := &InteractivePrompt{rl: state.rl}
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
		prompt := &InteractivePrompt{rl: state.rl}
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
		return err
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
		prompt := &InteractivePrompt{rl: state.rl}
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
		prompt := &InteractivePrompt{rl: state.rl}
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
		prompt := &InteractivePrompt{rl: state.rl}
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
		return err
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
		prompt := &InteractivePrompt{rl: state.rl}
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
		return err
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
	fmt.Printf("Messages for group %s:\n", groupID)
	for _, msg := range result.Items {
		fmt.Println(formatMessage(msg))
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
		prompt := &InteractivePrompt{rl: state.rl}
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
		prompt := &InteractivePrompt{rl: state.rl}
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
		prompt := &InteractivePrompt{rl: state.rl}
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
		return err
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
		prompt := &InteractivePrompt{rl: state.rl}
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
		prompt := &InteractivePrompt{rl: state.rl}
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
		return err
	}

	printSuccess("Message deleted")
	return nil
}

// --- Other commands ---

func handleHelp(args []string, state *CLIState) error {
	fmt.Println(yellow("Available commands:"))
	printSeparator()
	fmt.Println("Group commands:")
	fmt.Println("  /group:list     List all groups")
	fmt.Println("  /group:create   Create a new group")
	fmt.Println("  /group:enter    Enter a group chat")
	fmt.Println("  /group:update   Update a group")
	fmt.Println("  /group:delete   Delete a group")
	fmt.Println()
	fmt.Println("Member commands:")
	fmt.Println("  /member:list    List group members")
	fmt.Println("  /member:add     Add a member to a group")
	fmt.Println("  /member:remove  Remove a member from a group")
	fmt.Println("  /member:update  Update a member")
	fmt.Println()
	fmt.Println("Message commands:")
	fmt.Println("  /message:list   List messages in a group")
	fmt.Println("  /message:edit   Edit a message")
	fmt.Println("  /message:delete Delete a message")
	fmt.Println()
	fmt.Println("Other commands:")
	fmt.Println("  /help           Show this help")
	fmt.Println("  /exit           Exit the CLI")
	fmt.Println("  exit, quit      Aliases for /exit")
	printSeparator()
	fmt.Println("Interactive mode: type a command without arguments to be prompted.")
	fmt.Println("Non-interactive mode: /command --arg value")
	return nil
}

func handleExit(args []string, state *CLIState) error {
	state.running = false
	return nil
}
