// Package main provides chat mode for the ACS chat CLI.
package main

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"time"
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
		if err := app.nats.Connect(); err == nil {
			app.nats.onMessage = app.handleIncomingMessage
			app.nats.onMember = app.handleMemberEvent
			_ = app.nats.SubscribeGroup(groupID)
		}
	}
	return app.chatLoop(ctx)
}

func (app *App) chatLoop(ctx context.Context) error {
	pollInterval := 2 * time.Second
	ticker := time.NewTicker(pollInterval)
	defer ticker.Stop()
	msgCh := make(chan string, 1)
	var wg sync.WaitGroup
	wg.Add(1)
	go func() {
		defer wg.Done()
		for {
			app.rl.SetPrompt(app.prompt.String())
			line, err := app.rl.Readline()
			if err != nil {
				if strings.Contains(err.Error(), "interrupt") {
					continue
				}
				return
			}
			line = strings.TrimSpace(line)
			if line == "" {
				continue
			}
			if line == "/group leave" || line == "/leave" {
				msgCh <- "__leave__"
				return
			}
			if line == "/member list" || line == "/members" {
				msgCh <- "__members__"
				continue
			}
			if strings.HasPrefix(line, "/member add ") {
				msgCh <- "__member_add__" + line[len("/member add "):]
				continue
			}
			if line == "/help" {
				msgCh <- "__help__"
				continue
			}
			if line == "exit" || line == "quit" {
				msgCh <- "__exit__"
				return
			}
			msgCh <- line
		}
	}()
	defer wg.Wait()
	for {
		select {
		case line := <-msgCh:
			switch {
			case line == "__leave__":
				return app.LeaveCurrentGroup(ctx)
			case line == "__members__":
				if err := app.ListMembers(ctx); err != nil {
					app.display.PrintError(err, "/member list")
				}
			case strings.HasPrefix(line, "__member_add__"):
				args := strings.TrimSpace(strings.TrimPrefix(line, "__member_add__"))
				if err := app.handleMemberAddInline(ctx, args); err != nil {
					app.display.PrintError(err, "/member add")
				}
			case line == "__help__":
				printChatHelp(app)
			case line == "__exit__":
				return errExit
			default:
				if err := app.sendMessage(ctx, line); err != nil {
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
}

func (app *App) handleMemberEvent(member Member) {
	if app.currentGroup == nil || member.GroupID != app.currentGroup.GroupID {
		return
	}
	_ = app.refreshMembers(context.Background())
}

func printChatHelp(app *App) {
	fmt.Println(app.display.Info("Chat Mode Commands"))
	fmt.Println()
	fmt.Println("  @<name>                  Mention a member")
	fmt.Println("  /member list             List members of current group")
	fmt.Println("  /members                 Alias for /member list")
	fmt.Println("  /group leave             Leave current group chat")
	fmt.Println("  /help                    Show this help")
	fmt.Println("  exit | quit              Exit the CLI")
}
