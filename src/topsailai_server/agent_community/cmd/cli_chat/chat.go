// Package main provides chat mode for the ACS chat CLI.
package main

import (
	"context"
	"errors"
	"fmt"
	"io"
	"strings"
	"sync"
	"time"

	"github.com/chzyer/readline"
)

// EnterChat enters a group chat session.
func (app *App) EnterChat(ctx context.Context, groupID string) error {
	group, err := app.client.GetGroup(ctx, groupID)
	if err != nil {
		return fmt.Errorf("failed to enter group: %w", err)
	}
	app.currentGroup = group
	app.prompt.SetGroup(group.GroupID)
	fmt.Println(app.display.Info(fmt.Sprintf("Entered group %s (%s)", group.GroupID, group.GroupName)))
	if err := app.refreshMembers(ctx); err != nil {
		fmt.Println(app.display.Warning(fmt.Sprintf("failed to load members: %v", err)))
	}
	if err := app.showRecentMessages(ctx); err != nil {
		fmt.Println(app.display.Warning(fmt.Sprintf("failed to load messages: %v", err)))
	}
	if app.nats != nil {
		if err := app.nats.Connect(); err != nil {
			return fmt.Errorf("failed to connect to NATS: %w", err)
		}
		if err := app.nats.SubscribeGroup(groupID); err != nil {
			return fmt.Errorf("failed to subscribe to group events: %w", err)
		}
	}
	return app.chatLoop(ctx)
}

func (app *App) chatLoop(ctx context.Context) error {
	pollInterval := 2 * time.Second
	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()

	type inputResult struct {
		line string
		err  error
	}
	inputCh := make(chan inputResult, 1)
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for {
			app.rl.SetPrompt(app.prompt.String())
			line, err := app.rl.Readline()
			if err != nil {
				if errors.Is(err, readline.ErrInterrupt) {
					continue
				}
				inputCh <- inputResult{err: err}
				return
			}
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			if line == "/group leave" || line == "/leave" {
				inputCh <- inputResult{line: "__leave__"}
				return
			}
			if line == "/member list" || line == "/members" {
				inputCh <- inputResult{line: "__members__"}
				continue
			}
			if strings.HasPrefix(line, "/member add ") {
				inputCh <- inputResult{line: "__member_add__" + line[len("/member add "):]}
				continue
			}
			if line == "/help" {
				inputCh <- inputResult{line: "__help__"}
				continue
			}
			if line == "exit" || line == "quit" {
				inputCh <- inputResult{line: "__exit__"}
				return
			}
			inputCh <- inputResult{line: line}
		}
	}()
	defer wg.Wait()

	var msgCh <-chan Message
	var memberCh <-chan Member
	if app.nats != nil {
		msgCh = app.nats.Messages()
		memberCh = app.nats.Members()
	}

	for {
		select {
		case msg := <-msgCh:
			app.handleIncomingMessage(msg)
		case member := <-memberCh:
			app.handleMemberEvent(member)
		case result := <-inputCh:
			if result.err != nil {
				if errors.Is(result.err, io.EOF) {
					return errExit
				}
				return result.err
			}
			switch {
			case result.line == "__leave__":
				return app.LeaveCurrentGroup(ctx)
			case result.line == "__members__":
				if err := app.ListMembers(ctx); err != nil {
					app.display.PrintError(err, "/member list")
				}
			case strings.HasPrefix(result.line, "__member_add__"):
				args := strings.TrimSpace(strings.TrimPrefix(result.line, "__member_add__"))
				if err := app.handleMemberAddInline(ctx, args); err != nil {
					app.display.PrintError(err, "/member add")
				}
			case result.line == "__help__":
				printChatHelp(app)
			case result.line == "__exit__":
				return errExit
			default:
				if err := app.sendMessage(ctx, result.line); err != nil {
					app.display.PrintError(err, "send message")
				}
			}
		case <-ticker.C:
			if app.nats == nil || !app.nats.IsConnected() {
				if err := app.showRecentMessages(ctx); err != nil {
					app.display.PrintError(err, "poll messages")
				}
			}
		case <-ctx.Done():
			return ctx.Err()
		}
	}
}

func (app *App) sendMessage(ctx context.Context, text string) error {
	if app.currentGroup == nil {
		return fmt.Errorf("not in a group chat")
	}
	msg, err := app.client.SendMessage(ctx, app.currentGroup.GroupID, text)
	if err != nil {
		return err
	}
	fmt.Println(app.display.Message(*msg, app.accountID))
	return nil
}

func (app *App) showRecentMessages(ctx context.Context) error {
	if app.currentGroup == nil {
		return nil
	}
	messages, err := app.client.ListMessages(ctx, app.currentGroup.GroupID, 50)
	if err != nil {
		return err
	}
	for _, msg := range messages {
		fmt.Println(app.display.Message(msg, app.accountID))
	}
	return nil
}

func (app *App) refreshMembers(ctx context.Context) error {
	if app.currentGroup == nil {
		return nil
	}
	members, err := app.client.ListMembers(ctx, app.currentGroup.GroupID)
	if err != nil {
		return err
	}
	app.members = members
	app.completer.SetMembers(members)
	app.statusBar.Update(members)
	return nil
}

func (app *App) handleIncomingMessage(msg Message) {
	if app.currentGroup == nil || msg.GroupID != app.currentGroup.GroupID {
		return
	}
	fmt.Println(app.display.Message(msg, app.accountID))
	if app.rl != nil {
		app.rl.Refresh()
	}
}

func (app *App) handleMemberEvent(member Member) {
	if app.currentGroup == nil || member.GroupID != app.currentGroup.GroupID {
		return
	}
	found := false
	for i, m := range app.members {
		if m.MemberID == member.MemberID {
			app.members[i] = member
			found = true
			break
		}
	}
	if !found {
		app.members = append(app.members, member)
	}
	app.completer.SetMembers(app.members)
	app.statusBar.Update(app.members)
}

func printChatHelp(app *App) {
	fmt.Println(app.display.Info("Chat commands:"))
	fmt.Println("  /member list        list group members")
	fmt.Println("  /member add <args>  add a member to the group")
	fmt.Println("  /group leave        leave the current group")
	fmt.Println("  /help               show this help")
	fmt.Println("  exit / quit         exit the application")
}
