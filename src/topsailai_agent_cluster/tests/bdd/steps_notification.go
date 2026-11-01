package bdd

import (
	"bufio"
	"context"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/cucumber/godog"
)

// registerNotificationSteps registers real SSE and manifest assertions.
func registerNotificationSteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^an isolated Agent Cluster server with notifications$`, func() error {
		activeScenario.world = NewWorld(activeTest)
		return activeScenario.world.startEvents()
	})
	ctx.Step(`^an inventory changed event for "([^"]*)" is observable$`, func(endpoint string) error {
		deadline := time.NewTimer(5 * time.Second)
		defer deadline.Stop()
		select {
		case event := <-activeScenario.world.events:
			if !strings.Contains(string(event), endpoint) {
				return fmt.Errorf("event %q does not identify %q", event, endpoint)
			}
			return nil
		case <-deadline.C:
			return fmt.Errorf("event for %q not observed", endpoint)
		}
	})
	ctx.Step(`^the manifest reports revision (\d+) for "([^"]*)"$`, func(revision int64, endpoint string) error {
		resp, body := activeScenario.world.Request(activeTest, http.MethodGet, "/api/v1/manifest", nil)
		if resp.StatusCode != http.StatusOK {
			return fmt.Errorf("manifest status %d", resp.StatusCode)
		}
		if !strings.Contains(string(body), endpoint) || !strings.Contains(string(body), fmt.Sprintf(`"snapshot_revision":%d`, revision)) {
			return fmt.Errorf("manifest does not contain %s revision %d", endpoint, revision)
		}
		return nil
	})
}

// startEvents subscribes before the scenario's When step commits an inventory update.
func (w *World) startEvents() error {
	w.events = make(chan []byte, 1)
	go func() {
		request, err := http.NewRequestWithContext(context.Background(), http.MethodGet, w.URL("/api/v1/events"), nil)
		if err != nil {
			return
		}
		request.Header.Set("Authorization", "Bearer "+w.Token)
		response, err := w.Client.Do(request)
		if err != nil {
			return
		}
		defer response.Body.Close()
		if response.StatusCode != http.StatusOK {
			return
		}
		scanner := bufio.NewScanner(response.Body)
		var data string
		for scanner.Scan() {
			line := scanner.Text()
			if strings.HasPrefix(line, "data: ") {
				data = strings.TrimPrefix(line, "data: ")
			}
			if line == "" && data != "" {
				w.events <- []byte(data)
				return
			}
		}
	}()
	return nil
}
