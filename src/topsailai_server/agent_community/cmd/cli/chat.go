// Package main provides chat window mode for the ACS CLI terminal.
package main

import (
	"fmt"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/chzyer/readline"
	"github.com/topsailai/agent-community/internal/nats"
)

// ChatMode manages the chat window state.
type ChatMode struct {
	groupID     string
	userID      string
	userName    string
	natsManager *NATSManager
	apiClient   *APIClient
	rl          *readline.Instance
	active      bool
	mu          sync.Mutex
	members     []map[string]interface{}
	eventCh     chan *nats.PendingPublishMessage
	inputCh     chan string
	oldHandler  func(*nats.PendingPublishMessage)
}

// NewChatMode creates a new chat mode manager.
func NewChatMode(apiClient *APIClient, natsManager *NATSManager) *ChatMode {
	return &ChatMode{
		apiClient:   apiClient,
		natsManager: natsManager,
		eventCh:     make(chan *nats.PendingPublishMessage, 100),
		inputCh:     make(chan string),
	}
}

// EnterChat enters the chat window for a group.
func (cm *ChatMode) EnterChat(groupID, userID, userName string) error {
	cm.groupID = groupID
	cm.userID = userID
	cm.userName = userName
	cm.active = true

	// Fetch and cache member list for mention resolution.
	if err := cm.refreshMembers(); err != nil {
		printWarning(fmt.Sprintf("Failed to fetch members: %v", err))
	}

	// Subscribe to group events.
	if err := cm.natsManager.SubscribeGroup(groupID); err != nil {
		printWarning(fmt.Sprintf("Failed to subscribe: %v", err))
	}

	// Override event handler to route events to chat channel.
	cm.oldHandler = cm.natsManager.onEvent
	cm.natsManager.onEvent = func(event *nats.PendingPublishMessage) {
		select {
		case cm.eventCh <- event:
		default:
		}
		if cm.oldHandler != nil {
			cm.oldHandler(event)
		}
	}

	// Create readline with chat PS1.
	rl, err := readline.New(ps1Chat(userName, groupID))
	if err != nil {
		cm.restoreHandler()
		cm.natsManager.Unsubscribe()
		return fmt.Errorf("failed to create readline: %w", err)
	}
	cm.rl = rl

	printSuccess(fmt.Sprintf("Entered chat mode for group %s", groupID))
	printInfo("Type your message and press Enter to send.")
	printInfo("Commands: /members, /exit")

	// Start input reader goroutine.
	go cm.readInput()

	// Main event loop.
	for cm.active {
		select {
		case event := <-cm.eventCh:
			cm.displayEvent(event)
		case line, ok := <-cm.inputCh:
			if !ok {
				cm.LeaveChat()
				return nil
			}
			cm.handleInput(line)
		}
	}

	return nil
}

// readInput reads lines from readline and sends to inputCh.
func (cm *ChatMode) readInput() {
	for {
		line, err := cm.rl.Readline()
		if err != nil {
			close(cm.inputCh)
			return
		}
		cm.inputCh <- line
	}
}

// handleInput processes user input in chat mode.
func (cm *ChatMode) handleInput(line string) {
	line = strings.TrimSpace(line)
	if line == "" {
		return
	}

	switch line {
	case "/exit", "exit", "quit":
		cm.LeaveChat()
		return
	case "/members":
		cm.showMembers()
	case "/help":
		cm.showChatHelp()
	default:
		if strings.HasPrefix(line, "/") {
			printError(fmt.Sprintf("Unknown command: %s", line))
			return
		}
		if err := cm.SendChatMessage(line); err != nil {
			printError(fmt.Sprintf("Failed to send: %v", err))
		}
	}
}

// SendChatMessage sends a message to the group with mention parsing.
func (cm *ChatMode) SendChatMessage(text string) error {
	mentions := cm.parseMentions(text)

	payload := map[string]interface{}{
		"message_text": text,
		"sender_id":    cm.userID,
		"sender_type":  "user",
	}
	if len(mentions) > 0 {
		payload["mentions"] = mentions
	}

	_, err := cm.apiClient.Post(fmt.Sprintf("/api/v1/groups/%s/messages", cm.groupID), payload)
	if err != nil {
		return err
	}

	// Display locally.
	fmt.Println(formatMessage(map[string]interface{}{
		"sender_id":    cm.userID,
		"sender_name":  cm.userName,
		"sender_type":  "user",
		"message_text": text,
		"create_at_ms": float64(time.Now().UnixMilli()),
	}))
	return nil
}

// LeaveChat leaves the chat mode and cleans up.
func (cm *ChatMode) LeaveChat() {
	cm.mu.Lock()
	if !cm.active {
		cm.mu.Unlock()
		return
	}
	cm.active = false
	cm.mu.Unlock()

	cm.natsManager.Unsubscribe()
	cm.restoreHandler()

	if cm.rl != nil {
		cm.rl.Close()
		cm.rl = nil
	}

	printInfo(fmt.Sprintf("Left chat mode for group %s", cm.groupID))
}

// restoreHandler restores the original NATS event handler.
func (cm *ChatMode) restoreHandler() {
	if cm.natsManager != nil {
		cm.natsManager.onEvent = cm.oldHandler
	}
}

// refreshMembers fetches and caches the member list.
func (cm *ChatMode) refreshMembers() error {
	resp, err := cm.apiClient.ListMembers(cm.groupID, ListQuery{Limit: 1000})
	if err != nil {
		return err
	}

	var result struct {
		Items []map[string]interface{} `json:"items"`
	}
	if err := resp.GetData(&result); err != nil {
		return err
	}

	cm.mu.Lock()
	cm.members = result.Items
	cm.mu.Unlock()
	return nil
}

// showMembers displays the cached member list.
func (cm *ChatMode) showMembers() {
	cm.mu.Lock()
	members := cm.members
	cm.mu.Unlock()

	if len(members) == 0 {
		printInfo("No members in this group.")
		return
	}

	printSeparator()
	fmt.Println("Members:")
	for _, m := range members {
		id, _ := m["member_id"].(string)
		name, _ := m["member_name"].(string)
		mtype, _ := m["member_type"].(string)
		status, _ := m["member_status"].(string)
		fmt.Println(formatMemberLine(mtype, name, id, status))
	}
	printSeparator()
}

// showChatHelp displays available chat commands.
func (cm *ChatMode) showChatHelp() {
	printSeparator()
	fmt.Println("Chat Commands:")
	fmt.Println("  /members  - Show group members")
	fmt.Println("  /help     - Show this help")
	fmt.Println("  /exit     - Leave chat mode")
	fmt.Println("  exit      - Alias for /exit")
	fmt.Println("  quit      - Alias for /exit")
	fmt.Println("  (any text) - Send a message to the group")
	printSeparator()
}

// displayEvent displays a NATS event in chat mode.
func (cm *ChatMode) displayEvent(event *nats.PendingPublishMessage) {
	if event.GroupID != "" && event.GroupID != cm.groupID {
		return
	}

	switch event.Type {
	case "message":
		data, ok := event.Data.(map[string]interface{})
		if !ok {
			return
		}
		action := event.Action
		if action == "delete" {
			data["is_deleted"] = true
		}
		if action == "modify" {
			text, _ := data["message_text"].(string)
			data["message_text"] = text + " [edited]"
		}
		fmt.Println(formatMessage(data))
	case "group_member":
		// Refresh members on member changes.
		go cm.refreshMembers()
		fmt.Println(formatMemberEvent(event.Action, event.GroupID))
	default:
		fmt.Println(formatGenericEvent(event.Type, event.Action, event.GroupID))
	}

	// Refresh readline prompt to redraw after async output.
	if cm.rl != nil {
		cm.rl.Refresh()
	}
}

// mentionRegex matches @word patterns, excluding trailing punctuation.
var mentionRegex = regexp.MustCompile(`@([^\s,.!?;:\n]+)`)

// parseMentions extracts mentions from message text.
func (cm *ChatMode) parseMentions(text string) []map[string]interface{} {
	matches := mentionRegex.FindAllStringSubmatch(text, -1)
	if len(matches) == 0 {
		return nil
	}

	cm.mu.Lock()
	members := cm.members
	cm.mu.Unlock()

	mentions := make([]map[string]interface{}, 0, len(matches))
	seen := make(map[string]bool)

	for _, m := range matches {
		target := m[1]

		var memberID, memberName, memberType string
		found := false
		for _, member := range members {
			id, _ := member["member_id"].(string)
			name, _ := member["member_name"].(string)
			mtype, _ := member["member_type"].(string)
			if id == target || name == target {
				memberID = id
				memberName = name
				memberType = mtype
				found = true
				break
			}
		}

		if !found {
			memberID = target
			memberName = target
			memberType = "user"
		}

		// Deduplicate by resolved member_id.
		if seen[memberID] {
			continue
		}
		seen[memberID] = true

		mentions = append(mentions, map[string]interface{}{
			"member_id":   memberID,
			"member_name": memberName,
			"member_type": memberType,
		})
	}

	return mentions
}
