// Package main provides display and formatting utilities for the ACS CLI terminal.
package main

import (
	"fmt"
	"os"
	"strings"
	"time"
)

const (
	colorReset      = "\033[0m"
	colorRed        = "\033[1;31m"
	colorGreen      = "\033[1;32m"
	colorYellow     = "\033[1;33m"
	colorBlue       = "\033[1;34m"
	colorCyan       = "\033[1;36m"
	colorWhite      = "\033[1;37m"
	colorBold       = "\033[1m"
	colorBoldReset  = "\033[22m"
)
// noColor disables ANSI color output when true.
var noColor bool

// initColor checks --no-color flag and NO_COLOR environment variable.
func initColor(args []string) {
	for _, arg := range args {
		if arg == "--no-color" {
			noColor = true
			return
		}
	}
	if os.Getenv("NO_COLOR") != "" {
		noColor = true
	}
}

// colorize wraps text with ANSI color codes if colors are enabled.
func colorize(text, color string) string {
	if noColor {
		return text
	}
	return color + text + colorReset
}

// red returns red-colored text.
func red(text string) string {
	return colorize(text, colorRed)
}

// green returns green-colored text.
func green(text string) string {
	return colorize(text, colorGreen)
}

// yellow returns yellow-colored text.
func yellow(text string) string {
	return colorize(text, colorYellow)
}

// blue returns blue-colored text.
func blue(text string) string {
	return colorize(text, colorBlue)
}

// cyan returns cyan-colored text.
func cyan(text string) string {
	return colorize(text, colorCyan)
}

// white returns white-colored text.
func white(text string) string {
	return colorize(text, colorWhite)
}

// formatTime formats a timestamp as YYYY-MM-DDTHH:MM:SS.
func formatTime(t time.Time) string {
	return t.Format("2006-01-02T15:04:05")
}

// formatTimeMs formats a Unix millisecond timestamp as YYYY-MM-DDTHH:MM:SS.
func formatTimeMs(ms int64) string {
	return time.UnixMilli(ms).UTC().Format("2006-01-02T15:04:05")
}

// formatTimeMsFloat formats a float64 Unix millisecond timestamp as YYYY-MM-DDTHH:MM:SS.
func formatTimeMsFloat(ms float64) string {
	return formatTimeMs(int64(ms))
}

// ps1Normal returns the normal mode prompt: acs@{userName}({userID})[role]:
func ps1Normal(userName, userID, role string) string {
	if role != "" {
		if noColor {
			return fmt.Sprintf("acs@%s(%s)[%s]: ", userName, userID, role)
		}
		return yellow(fmt.Sprintf("acs@%s(%s)[%s]: ", userName, userID, role))
	}
	if noColor {
		return fmt.Sprintf("acs@%s(%s): ", userName, userID)
	}
	return yellow(fmt.Sprintf("acs@%s(%s): ", userName, userID))
}

// ps1Chat returns the chat mode prompt: acs@{userName}({userID})[role]:{groupId}#
func ps1Chat(userName, userID, role, groupID string) string {
	if role != "" {
		if noColor {
			return fmt.Sprintf("acs@%s(%s)[%s]:%s# ", userName, userID, role, groupID)
		}
		return yellow(fmt.Sprintf("acs@%s(%s)[%s]:%s# ", userName, userID, role, groupID))
	}
	if noColor {
		return fmt.Sprintf("acs@%s(%s):%s# ", userName, userID, groupID)
	}
	return yellow(fmt.Sprintf("acs@%s(%s):%s# ", userName, userID, groupID))
}

// boxHorizontal returns the horizontal border character used for separators and boxes.
func boxHorizontal() string {
	if noColor {
		return "-"
	}
	return "─"
}

// boxDoubleHorizontal returns the double horizontal border character.
func boxDoubleHorizontal() string {
	if noColor {
		return "="
	}
	return "═"
}

// bannerBorder returns the top, middle, and bottom banner border lines.
// When colors are disabled, plain ASCII borders are used so that --no-color
// also suppresses Unicode box-drawing characters.
func bannerBorder() (top, middle, bottom string) {
	if noColor {
		top = "+------------------------------------------+"
		middle = "|     ACS CLI Terminal                     |"
		bottom = "+------------------------------------------+"
		return
	}
	top = "╔══════════════════════════════════════════╗"
	middle = "║     ACS CLI Terminal                     ║"
	bottom = "╚══════════════════════════════════════════╝"
	return
}

// printBanner prints the ACS CLI welcome banner.
func printBanner() {
	top, middle, bottom := bannerBorder()
	promptPrintLines(
		cyan(top),
		cyan(middle),
		cyan(bottom),
	)
}

// printInfo prints an informational message.
func printInfo(msg string) {
	promptPrintln(blue(msg))
}

// printSuccess prints a success message.
func printSuccess(msg string) {
	promptPrintln(green(msg))
}

// printError prints an error message.
func printError(msg string) {
	promptPrintln(red(msg))
}

// printWarning prints a warning message.
func printWarning(msg string) {
	promptPrintln(yellow(msg))
}

// printSeparator prints a horizontal separator line.
func printSeparator() {
	promptPrintln(white(strings.Repeat(boxHorizontal(), 42)))
}

// printDoubleSeparator prints a double horizontal separator line.
func printDoubleSeparator() {
	promptPrintln(white(strings.Repeat(boxDoubleHorizontal(), 42)))
}

// agentIcon returns the icon or label used for agent senders.
func agentIcon() string {
	if noColor {
		return "[BOT]"
	}
	return "🤖"
}

// eventIcon returns the icon or label used for group events.
func eventIcon() string {
	if noColor {
		return "[EVENT]"
	}
	return "📢"
}

// memberIcon returns the icon or label used for member events.
func memberIcon() string {
	if noColor {
		return "[MEMBER]"
	}
	return "👤"
}

// genericEventIcon returns the icon or label used for generic NATS events.
func genericEventIcon() string {
	if noColor {
		return "[EVENT]"
	}
	return "📰"
}

// formatMessage formats a single message for display.
func formatMessage(msg map[string]interface{}) string {
	senderID, _ := msg["sender_id"].(string)
	senderName, _ := msg["sender_name"].(string)
	senderType, _ := msg["sender_type"].(string)
	messageText, _ := msg["message_text"].(string)
	createAtMsFloat, _ := msg["create_at_ms"].(float64)
	isDeleted, _ := msg["is_deleted"].(bool)

	if isDeleted {
		messageText = "[message deleted]"
	}

	timestamp := formatTimeMsFloat(createAtMsFloat)

	displayName := senderName
	if displayName == "" {
		displayName = senderID
	}

	var prefix string
	switch senderType {
	case "user":
		prefix = fmt.Sprintf("[%s] %s", cyan(timestamp), white(displayName))
	case "manager-agent", "worker-agent":
		prefix = fmt.Sprintf("[%s] %s %s", cyan(timestamp), green(agentIcon()), green(displayName))
	default:
		prefix = fmt.Sprintf("[%s] %s", cyan(timestamp), white(displayName))
	}

	return fmt.Sprintf("%s\n  %s", prefix, messageText)
}

// formatGroupEvent formats a group event for display.
func formatGroupEvent(action, groupID string) string {
	timestamp := formatTime(time.Now())
	return fmt.Sprintf("[%s] %s Group event: %s %s", cyan(timestamp), yellow(eventIcon()), action, white(groupID))
}

// formatMemberEvent formats a member event for display.
func formatMemberEvent(action, groupID string) string {
	timestamp := formatTime(time.Now())
	return fmt.Sprintf("[%s] %s Member event: %s %s", cyan(timestamp), blue(memberIcon()), action, white(groupID))
}

// formatGenericEvent formats a generic NATS event for display.
func formatGenericEvent(eventType, action, groupID string) string {
	timestamp := formatTime(time.Now())
	return fmt.Sprintf("[%s] %s Event: %s %s %s", cyan(timestamp), blue(genericEventIcon()), eventType, action, white(groupID))
}

// formatGroupLine formats a group list item.
func formatGroupLine(groupID, groupName string) string {
	return fmt.Sprintf("  %s  %s", white(groupID), green(groupName))
}

// formatMemberLine formats a member list item.
func formatMemberLine(memberType, memberName, memberID, memberStatus string) string {
	var typeColor func(string) string
	switch memberType {
	case "user":
		typeColor = blue
	case "manager-agent":
		typeColor = yellow
	case "worker-agent":
		typeColor = green
	default:
		typeColor = white
	}
	return fmt.Sprintf("  [%s] %s (%s) - %s", typeColor(memberType), white(memberName), white(memberID), cyan(memberStatus))
}

// formatAccountLine formats an account list item.
func formatAccountLine(account map[string]interface{}) string {
	id, _ := account["account_id"].(string)
	name, _ := account["account_name"].(string)
	role, _ := account["role"].(string)
	status, _ := account["status"].(string)
	email, _ := account["email"].(string)
	if email == "" {
		email = "-"
	}
	return fmt.Sprintf("  %s %s [%s] (%s) <%s>", white(id), green(name), cyan(role), blue(status), white(email))
}

// formatAccountDetail formats full account details for display.
func formatAccountDetail(account map[string]interface{}) string {
	var b strings.Builder
	b.WriteString(printableSeparator())
	b.WriteString("\n")
	writeField(&b, "Account ID", account["account_id"])
	writeField(&b, "Name", account["account_name"])
	writeField(&b, "Description", account["account_description"])
	writeField(&b, "Role", account["role"])
	writeField(&b, "Status", account["status"])
	writeField(&b, "Login Name", account["login_name"])
	writeField(&b, "Email", account["email"])
	writeField(&b, "External ID", account["external_id"])
	writeField(&b, "Auth Provider", account["auth_provider"])
	writeField(&b, "Avatar URL", account["avatar_url"])
	writeField(&b, "Creator ID", account["creator_id"])
	if ms, ok := account["create_at_ms"].(float64); ok {
		writeField(&b, "Created", formatTimeMs(int64(ms)))
	}
	if ms, ok := account["update_at_ms"].(float64); ok {
		writeField(&b, "Updated", formatTimeMs(int64(ms)))
	}
	b.WriteString(printableSeparator())
	return b.String()
}

// formatAPIKeyLine formats an API key list item.
func formatAPIKeyLine(key map[string]interface{}) string {
	id, _ := key["api_key_id"].(string)
	name, _ := key["api_key_name"].(string)
	role, _ := key["role"].(string)
	status, _ := key["status"].(string)
	return fmt.Sprintf("  %s %s [%s] (%s)", white(id), green(name), cyan(role), blue(status))
}

// formatAPIKeyDetail formats full API key details for display.
func formatAPIKeyDetail(key map[string]interface{}) string {
	var b strings.Builder
	b.WriteString(printableSeparator())
	b.WriteString("\n")
	writeField(&b, "API Key ID", key["api_key_id"])
	writeField(&b, "Name", key["api_key_name"])
	writeField(&b, "Role", key["role"])
	writeField(&b, "Status", key["status"])
	writeField(&b, "Token", key["token"])
	writeField(&b, "Owner ID", key["owner_id"])
	writeField(&b, "Creator ID", key["creator_id"])
	b.WriteString(printableSeparator())
	return b.String()
}

// formatSessionInfo formats a login session response for display.
func formatSessionInfo(session map[string]interface{}) string {
	var b strings.Builder
	b.WriteString(printableSeparator())
	b.WriteString("\n")
	writeField(&b, "Account ID", session["account_id"])
	writeField(&b, "Account Name", session["account_name"])
	writeField(&b, "Role", session["role"])
	writeField(&b, "Session Key", session["session_key"])
	if ms, ok := session["login_session_expired_time"].(float64); ok {
		writeField(&b, "Expires", formatTimeMs(int64(ms)))
	}
	b.WriteString(printableSeparator())
	return b.String()
}

// writeField appends a labeled field to the builder if the value is non-empty.
func writeField(b *strings.Builder, label string, value interface{}) {
	if value == nil {
		return
	}
	s, ok := value.(string)
	if ok && s == "" {
		return
	}
	if !ok {
		s = fmt.Sprintf("%v", value)
	}
	b.WriteString(fmt.Sprintf("%s: %s\n", cyan(label), white(s)))
}

// printableSeparator returns a plain separator string suitable for builders.
func printableSeparator() string {
	return strings.Repeat(boxHorizontal(), 42)
}
