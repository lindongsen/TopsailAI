// Package main provides chat window mode for the ACS CLI terminal.
package main

import (
	"fmt"
	"io"
	"os"
	"regexp"
	"strings"
	"sync"
	"time"

	"github.com/chzyer/readline"
	"github.com/topsailai/agent-community/internal/nats"
)

// natsManager abstracts the NATS subscription handling needed by ChatMode.
// It is satisfied by *NATSManager and by test doubles.
type natsManager interface {
	SubscribeGroup(groupID string) error
	Unsubscribe() error
	SetOnEvent(handler func(*nats.PendingPublishMessage))
	GetOnEvent() func(*nats.PendingPublishMessage)
}

// ChatMode manages the chat window state.
type ChatMode struct {
	groupID         string
	userID          string
	userName        string
	natsManager     natsManager
	apiClient       *APIClient
	rl              *readline.Instance
	active          bool
	mu              sync.Mutex
	members         []map[string]interface{}
	displayedMsgIDs map[string]struct{}
	eventCh         chan *nats.PendingPublishMessage
	inputCh         chan string
	doneCh          chan struct{}
	oldHandler      func(*nats.PendingPublishMessage)
	out             io.Writer
}

// NewChatMode creates a new chat mode manager.
func NewChatMode(apiClient *APIClient, natsManager natsManager) *ChatMode {
	return &ChatMode{
		apiClient:       apiClient,
		natsManager:     natsManager,
		displayedMsgIDs: make(map[string]struct{}),
		eventCh:         make(chan *nats.PendingPublishMessage, 100),
		out:             os.Stdout,
	}
}

// output helpers write to the configured writer so ChatMode is testable.
// If no writer is configured they fall back to os.Stdout for safety.
func (cm *ChatMode) output() io.Writer {
	if cm.out != nil {
		return cm.out
	}
	return os.Stdout
}

func (cm *ChatMode) println(a ...interface{}) {
	fmt.Fprintln(cm.output(), a...)
}

func (cm *ChatMode) printf(format string, a ...interface{}) {
	fmt.Fprintf(cm.output(), format, a...)
}

func (cm *ChatMode) printInfo(msg string) {
	fmt.Fprintln(cm.output(), blue(msg))
}

func (cm *ChatMode) printSuccess(msg string) {
	fmt.Fprintln(cm.output(), green(msg))
}

func (cm *ChatMode) printWarning(msg string) {
	fmt.Fprintln(cm.output(), yellow(msg))
}

func (cm *ChatMode) printError(msg string) {
	fmt.Fprintln(cm.output(), red(msg))
}

func (cm *ChatMode) printSeparator() {
	fmt.Fprintln(cm.output(), white(strings.Repeat(boxHorizontal(), 42)))
}
// EnterChat enters the chat window for a group.
func (cm *ChatMode) EnterChat(groupID, userID, userName string) error {
	cm.groupID = groupID
	cm.userID = userID
	cm.userName = userName
	cm.active = true

	// Create fresh channels for this chat session so re-entering does not
	// reuse a closed channel from a previous session.
	cm.inputCh = make(chan string)
	cm.doneCh = make(chan struct{})
	// Fetch and cache member list for mention resolution.
	if err := cm.refreshMembers(); err != nil {
		cm.printWarning(fmt.Sprintf("Failed to fetch members: %v", err))
	}

	// Subscribe to group events.
	if err := cm.natsManager.SubscribeGroup(groupID); err != nil {
		cm.printWarning(fmt.Sprintf("Failed to subscribe: %v", err))
	}

	// Override event handler to route events to chat channel.
	cm.oldHandler = cm.natsManager.GetOnEvent()
	cm.natsManager.SetOnEvent(func(event *nats.PendingPublishMessage) {
		select {
		case cm.eventCh <- event:
		default:
		}
		if cm.oldHandler != nil {
			cm.oldHandler(event)
		}
	})
	// Create readline with chat PS1 and auto-completion.
	rl, err := readline.NewEx(&readline.Config{
		Prompt: ps1Chat(userName, userID, "", groupID),
		AutoComplete: newChatMentionCompleter(func() []map[string]interface{} {
			cm.mu.Lock()
			defer cm.mu.Unlock()
			return cm.members
		}),
	})
	if err != nil {
		cm.restoreHandler()
		cm.natsManager.Unsubscribe()
		return fmt.Errorf("failed to create readline: %w", err)
	}
	cm.rl = rl

	cm.printSuccess(fmt.Sprintf("Entered chat mode for group %s", groupID))
	cm.printInfo("Type your message and press Enter to send.")
	cm.printInfo("Commands: /members, /exit")

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
// It exits when the readline instance returns an error or when doneCh is closed.
func (cm *ChatMode) readInput() {
	for {
		select {
		case <-cm.doneCh:
			return
		default:
		}

		line, err := cm.rl.Readline()
		if err != nil {
			// Signal the main loop to leave chat mode without closing the
			// channel here; LeaveChat will perform cleanup.
			cm.LeaveChat()
			return
		}

		select {
		case cm.inputCh <- line:
		case <-cm.doneCh:
			return
		}
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
			cm.printError(fmt.Sprintf("Unknown command: %s", line))
			return
		}
		if err := cm.SendChatMessage(line); err != nil {
			cm.printError(fmt.Sprintf("Failed to send: %v", err))
		}
	}
}

// SendChatMessage sends a message to the group. The server derives sender_id
// and sender_type from the authenticated account/session, so the client only
// sends the message text. Mentions are automatically extracted by the server.
func (cm *ChatMode) SendChatMessage(text string) error {
	resp, err := cm.apiClient.SendMessage(cm.groupID, text, nil)
	if err != nil {
		return err
	}

	// Try to extract message_id from the response so we can deduplicate the local echo.
	var msgResp map[string]interface{}
	if err := resp.GetData(&msgResp); err == nil {
		if msgID, ok := msgResp["message_id"].(string); ok && msgID != "" {
			cm.markMessageDisplayed(msgID)
		}
	}

	// Display locally using the authenticated account identity.
	cm.println(formatMessage(map[string]interface{}{
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

	// Signal the reader goroutine to stop. Do not close inputCh here to avoid
	// a panic if EnterChat is called again.
	if cm.doneCh != nil {
		close(cm.doneCh)
	}

	cm.natsManager.Unsubscribe()
	cm.restoreHandler()
	cm.clearDisplayedMessages()

	if cm.rl != nil {
		cm.rl.Close()
		cm.rl = nil
	}

	cm.printInfo(fmt.Sprintf("Left chat mode for group %s", cm.groupID))
}

// restoreHandler restores the original NATS event handler.
func (cm *ChatMode) restoreHandler() {
	if cm.natsManager != nil {
		cm.natsManager.SetOnEvent(cm.oldHandler)
	}
}

// isMessageDisplayed checks if a message has already been displayed.
func (cm *ChatMode) isMessageDisplayed(msgID string) bool {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	_, ok := cm.displayedMsgIDs[msgID]
	return ok
}

// markMessageDisplayed records a message ID as displayed.
func (cm *ChatMode) markMessageDisplayed(msgID string) {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.displayedMsgIDs[msgID] = struct{}{}
}

// clearDisplayedMessages clears the displayed message ID set.
func (cm *ChatMode) clearDisplayedMessages() {
	cm.mu.Lock()
	defer cm.mu.Unlock()
	cm.displayedMsgIDs = make(map[string]struct{})
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
		cm.printInfo("No members in this group.")
		return
	}

	cm.printSeparator()
	cm.println("Members:")
	for _, m := range members {
		id, _ := m["member_id"].(string)
		name, _ := m["member_name"].(string)
		mtype, _ := m["member_type"].(string)
		status, _ := m["member_status"].(string)
		cm.println(formatMemberLine(mtype, name, id, status))
	}
	cm.printSeparator()
}

// showChatHelp displays available chat commands.
func (cm *ChatMode) showChatHelp() {
	cm.printSeparator()
	cm.println("Chat Commands:")
	cm.println("  /members  - Show group members")
	cm.println("  /help     - Show this help")
	cm.println("  /exit     - Leave chat mode")
	cm.println("  exit      - Alias for /exit")
	cm.println("  quit      - Alias for /exit")
	cm.println("  (any text) - Send a message to the group")
	cm.printSeparator()
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
		msgID, _ := data["message_id"].(string)
		if msgID != "" && cm.isMessageDisplayed(msgID) {
			return
		}
		if msgID != "" {
			cm.markMessageDisplayed(msgID)
		}
		action := event.Action
		if action == "delete" {
			data["is_deleted"] = true
		}
		if action == "modify" {
			text, _ := data["message_text"].(string)
			data["message_text"] = text + " [edited]"
		}
		cm.println(formatMessage(data))
	case "group_member":
		// Refresh members on member changes.
		go cm.refreshMembers()
		cm.println(formatMemberEvent(event.Action, event.GroupID))
	default:
		cm.println(formatGenericEvent(event.Type, event.Action, event.GroupID))
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
