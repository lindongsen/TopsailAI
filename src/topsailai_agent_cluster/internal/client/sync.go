// Package client provides clients for latest-state Server APIs.
package client

import (
	"bufio"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"time"
)

// ManifestEntry identifies the latest persisted revision for one Endpoint.
type ManifestEntry struct {
	EndpointID       string `json:"endpoint_id"`
	SnapshotRevision int64  `json:"snapshot_revision"`
}

// Manifest is the latest-state synchronization document.
type Manifest struct {
	ServerInstanceID string          `json:"server_instance_id"`
	Entries          []ManifestEntry `json:"entries"`
}

// Event is a latest-state invalidation received from the Server.
type Event struct {
	Type             string `json:"type,omitempty"`
	EndpointID       string `json:"endpoint_id"`
	SnapshotRevision int64  `json:"snapshot_revision"`
	ServerInstanceID string `json:"server_instance_id"`
	Sequence         uint64 `json:"sequence"`
}

// Syncer reconciles latest Endpoint revisions from Server notifications.
type Syncer struct {
	httpClient       *http.Client
	baseURL          string
	bearerToken      string
	lastSequence     uint64
	serverInstanceID string
	sleep            func(context.Context, time.Duration) error
	backoffBase      time.Duration
	backoffMax       time.Duration
}

// NewSyncer constructs a latest-state client for baseURL.
func NewSyncer(baseURL, bearerToken string) *Syncer {
	return &Syncer{
		httpClient:  http.DefaultClient,
		baseURL:     strings.TrimRight(baseURL, "/"),
		bearerToken: bearerToken,
		sleep:       sleepWithContext,
		backoffBase: 200 * time.Millisecond,
		backoffMax:  5 * time.Second,
	}
}

// FetchManifest reads the current durable revision manifest.
func (s *Syncer) FetchManifest(ctx context.Context) (Manifest, error) {
	var manifest Manifest
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.baseURL+"/api/v1/manifest", nil)
	if err != nil {
		return manifest, err
	}
	s.authorize(req)
	resp, err := s.httpClient.Do(req)
	if err != nil {
		return manifest, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return manifest, fmt.Errorf("manifest request failed: %s", resp.Status)
	}
	if err := json.NewDecoder(resp.Body).Decode(&manifest); err != nil {
		return manifest, err
	}
	return manifest, nil
}

// Run subscribes to SSE and invokes onResync whenever reconciliation is required.
// Run synchronizes endpoint state until the context is cancelled.
func (s *Syncer) Run(ctx context.Context, onResync func(Manifest) error) error {
	manifest, recovered, err := s.fetchManifestWithRetry(ctx)
	if err != nil {
		return err
	}
	s.applyManifest(manifest)
	if recovered && onResync != nil {
		if callbackErr := onResync(manifest); callbackErr != nil {
			return callbackErr
		}
	}
	for attempt := 0; ; attempt++ {
		err := s.subscribe(ctx, onResync)
		if ctx.Err() != nil {
			return ctx.Err()
		}
		manifest, recovered, fetchErr := s.fetchManifestWithRetry(ctx)
		if fetchErr != nil {
			return fetchErr
		}
		instanceChanged := manifest.ServerInstanceID != s.serverInstanceID
		s.applyManifest(manifest)
		if (recovered || instanceChanged || err != io.EOF) && onResync != nil {
			if callbackErr := onResync(manifest); callbackErr != nil {
				return callbackErr
			}
		}
		delay := s.retryDelay(attempt)
		log.Printf("sync SSE reconnect reason=%q attempt=%d next_delay=%s", err, attempt+1, delay)
		if err := s.sleep(ctx, delay); err != nil {
			return err
		}
	}
}

func (s *Syncer) fetchManifestWithRetry(ctx context.Context) (Manifest, bool, error) {
	var manifest Manifest
	recovered := false
	for attempt := 0; ; attempt++ {
		var err error
		manifest, err = s.FetchManifest(ctx)
		if err == nil {
			return manifest, recovered, nil
		}
		if ctx.Err() != nil {
			return manifest, recovered, ctx.Err()
		}
		delay := s.retryDelay(attempt)
		log.Printf("sync manifest retry reason=%q attempt=%d next_delay=%s", err.Error(), attempt+1, delay)
		if err := s.sleep(ctx, delay); err != nil {
			return manifest, recovered, err
		}
		recovered = true
	}
}

func (s *Syncer) retryDelay(attempt int) time.Duration {
	delay := s.backoffBase
	for i := 0; i < attempt && delay < s.backoffMax; i++ {
		if delay > s.backoffMax/2 {
			return s.backoffMax
		}
		delay *= 2
	}
	if delay > s.backoffMax {
		return s.backoffMax
	}
	return delay
}

func sleepWithContext(ctx context.Context, delay time.Duration) error {
	timer := time.NewTimer(delay)
	defer timer.Stop()
	select {
	case <-ctx.Done():
		return ctx.Err()
	case <-timer.C:
		return nil
	}
}

func (s *Syncer) subscribe(ctx context.Context, onResync func(Manifest) error) error {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, s.baseURL+"/api/v1/events", nil)
	if err != nil {
		return err
	}
	s.authorize(req)
	resp, err := s.httpClient.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return fmt.Errorf("events request failed: %s", resp.Status)
	}
	return s.readSSE(ctx, resp.Body, onResync)
}

func (s *Syncer) readSSE(ctx context.Context, body io.Reader, onResync func(Manifest) error) error {
	scanner := bufio.NewScanner(body)
	var eventName, data string
	for scanner.Scan() {
		line := scanner.Text()
		if line == "" {
			if data != "" {
				if err := s.handleEvent(ctx, eventName, data, onResync); err != nil {
					return err
				}
			}
			eventName, data = "", ""
			continue
		}
		if strings.HasPrefix(line, "event:") {
			eventName = strings.TrimSpace(strings.TrimPrefix(line, "event:"))
		}
		if strings.HasPrefix(line, "data:") {
			data = strings.TrimSpace(strings.TrimPrefix(line, "data:"))
		}
	}
	if err := scanner.Err(); err != nil {
		return err
	}
	return io.EOF
}

func (s *Syncer) handleEvent(ctx context.Context, eventName, data string, onResync func(Manifest) error) error {
	var event Event
	if err := json.Unmarshal([]byte(data), &event); err != nil {
		return err
	}
	if event.Type == "" {
		event.Type = eventName
	}
	if event.Type == "resync_required" || (s.serverInstanceID != "" && event.ServerInstanceID != s.serverInstanceID) || (s.lastSequence != 0 && event.Sequence != s.lastSequence+1) {
		if err := s.reconcile(ctx, onResync); err != nil {
			return err
		}
	}
	s.serverInstanceID = event.ServerInstanceID
	s.lastSequence = event.Sequence
	return nil
}

func (s *Syncer) reconcile(ctx context.Context, onResync func(Manifest) error) error {
	manifest, err := s.FetchManifest(ctx)
	if err != nil {
		return err
	}
	s.applyManifest(manifest)
	if onResync != nil {
		if err := onResync(manifest); err != nil {
			return err
		}
	}
	return nil
}

func (s *Syncer) applyManifest(manifest Manifest) {
	s.serverInstanceID = manifest.ServerInstanceID
	s.lastSequence = 0
}

func (s *Syncer) authorize(req *http.Request) {
	if s.bearerToken != "" {
		req.Header.Set("Authorization", "Bearer "+s.bearerToken)
	}
}
