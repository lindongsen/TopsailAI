// Package main provides display and formatting utilities for the ACS CLI terminal.
package main

import (
	"fmt"
	"os"
	"time"
)

// ANSI color codes.
const (
	colorReset  = "\033[0m"
	colorRed    = "\033[31m"
	colorGreen  = "\033[32m"
	colorYellow = "\033[33m"
	colorBlue   = "\033[34m"
	colorCyan   = "\033[36m"
	colorWhite  = "\033[37m"
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

// ps1Normal returns the normal mode prompt: acs@{userName}: 
func ps1Normal(userName string) string {
	return yellow(fmt.Sprintf("acs@%s: ", userName))
}

// ps1Chat returns the chat mode prompt: acs@{userName}:{groupId}# 
func ps1Chat(userName, groupID string) string {
	return yellow(fmt.Sprintf("acs@%s:%s# ", userName, groupID))
}

// printBanner prints the ACS CLI welcome banner.
func printBanner() {
	fmt.Println(cyan("╔══════════════════════════════════════════╗"))
	fmt.Println(cyan("║     ACS CLI Terminal                     ║"))
	fmt.Println(cyan("╚══════════════════════════════════════════╝"))
}

// printInfo prints an informational message.
func printInfo(msg string) {
	fmt.Println(blue(msg))
}

// printSuccess prints a success message.
func printSuccess(msg string) {
	fmt.Println(green(msg))
}

// printError prints an error message.
func printError(msg string) {
	fmt.Println(red(msg))
}

// printWarning prints a warning message.
func printWarning(msg string) {
	fmt.Println(yellow(msg))
}

// printSeparator prints a horizontal separator line.
func printSeparator() {
	fmt.Println(white("──────────────────────────────────────────"))
}

// printDoubleSeparator prints a double horizontal separator line.
func printDoubleSeparator() {
	fmt.Println(white("══════════════════════════════════════════"))
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
		prefix = fmt.Sprintf("[%s] %s %s", cyan(timestamp), green("🤖"), green(displayName))
	default:
		prefix = fmt.Sprintf("[%s] %s", cyan(timestamp), white(displayName))
	}

	return fmt.Sprintf("%s\n  %s", prefix, messageText)
}

// formatGroupEvent formats a group event for display.
func formatGroupEvent(action, groupID string) string {
	timestamp := formatTime(time.Now())
	return fmt.Sprintf("[%s] %s Group event: %s %s", cyan(timestamp), yellow("📢"), action, white(groupID))
}

// formatMemberEvent formats a member event for display.
func formatMemberEvent(action, groupID string) string {
	timestamp := formatTime(time.Now())
	return fmt.Sprintf("[%s] %s Member event: %s %s", cyan(timestamp), blue("👤"), action, white(groupID))
}

// formatGenericEvent formats a generic NATS event for display.
func formatGenericEvent(eventType, action, groupID string) string {
	timestamp := formatTime(time.Now())
	return fmt.Sprintf("[%s] %s Event: %s %s %s", cyan(timestamp), blue("📡"), eventType, action, white(groupID))
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
