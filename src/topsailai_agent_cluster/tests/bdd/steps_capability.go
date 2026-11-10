package bdd

import (
	"context"
	"errors"
	"fmt"
	"os"
	"path/filepath"
	"sync"

	"github.com/cucumber/godog"
	"topsailai_agent_cluster/internal/adapter"
	topsailai "topsailai_agent_cluster/internal/adapter/topsailai"
	"topsailai_agent_cluster/internal/protocol"
)

// registerCapabilitySteps registers explicit unsupported and stop safety checks.
func registerCapabilitySteps(ctx *godog.ScenarioContext) {
	ctx.Step(`^an unsupported capability is requested$`, func() error {
		if activeScenario.world == nil {
			return errors.New("scenario server is not initialized")
		}
		status, body, err := activeScenario.world.UnsupportedCapability()
		if err != nil {
			return err
		}
		activeScenario.lastStatus, activeScenario.lastBody = status, body
		return nil
	})
	ctx.Step(`^the response is unsupported$`, func() error {
		if activeScenario.lastStatus != 501 || !containsText(activeScenario.lastBody, "unsupported") {
			return fmt.Errorf("expected unsupported response, status=%d body=%s", activeScenario.lastStatus, activeScenario.lastBody)
		}
		return nil
	})
	ctx.Step(`^stop is requested from an adapter without stop capability$`, func() error {
		if err := configureCapabilityAdapter(false); err != nil {
			return err
		}
		if err := executeStop("g1"); err != nil {
			return err
		}
		activeScenario.lastStatus = 501
		activeScenario.lastBody = []byte("unsupported")
		return nil
	})
	ctx.Step(`^no interrupt operation is attempted$`, func() error {
		if activeScenario.capabilityCalls != 0 {
			return fmt.Errorf("unexpected provider calls: %d", activeScenario.capabilityCalls)
		}
		return nil
	})
	ctx.Step(`^an adapter with missing pidfd platform capability$`, func() error {
		return configureCapabilityAdapter(false)
	})
	ctx.Step(`^stop is requested from that adapter$`, func() error {
		return executeStop("g1")
	})
	ctx.Step(`^the adapter response is unsupported$`, func() error {
		if !errors.Is(activeScenario.capabilityErr, adapter.ErrUnsupported) {
			return fmt.Errorf("want ErrUnsupported, got %v", activeScenario.capabilityErr)
		}
		return nil
	})
	ctx.Step(`^an adapter with stop platform capability$`, func() error {
		return configureCapabilityAdapter(true)
	})
	ctx.Step(`^stop is requested without a generation$`, func() error {
		return executeStop("")
	})
	ctx.Step(`^the adapter response reports generation required$`, func() error {
		if activeScenario.capabilityErr == nil || !containsText([]byte(activeScenario.capabilityErr.Error()), "generation") {
			return fmt.Errorf("want generation error, got %v", activeScenario.capabilityErr)
		}
		return nil
	})
}

type capabilityMapper struct {
	mu    sync.Mutex
	byKey map[string]adapter.ResourceMapping
	byID  map[string]adapter.ResourceMapping
}

func newCapabilityMapper() *capabilityMapper {
	return &capabilityMapper{byKey: make(map[string]adapter.ResourceMapping), byID: make(map[string]adapter.ResourceMapping)}
}

func (m *capabilityMapper) GetOrCreateResourceID(_ context.Context, adapterID, providerKey string, _ int64) (adapter.ResourceMapping, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	if mapping, ok := m.byKey[providerKey]; ok {
		return mapping, nil
	}
	mapping := adapter.ResourceMapping{AdapterID: adapterID, ProviderKey: providerKey, ResourceID: "res_" + providerKey}
	m.byKey[providerKey] = mapping
	m.byID[mapping.ResourceID] = mapping
	return mapping, nil
}

func (m *capabilityMapper) LookupResourceID(_ context.Context, resourceID string) (adapter.ResourceMapping, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	mapping, ok := m.byID[resourceID]
	if !ok {
		return adapter.ResourceMapping{}, fmt.Errorf("resource mapping %s not found", resourceID)
	}
	return mapping, nil
}

func configureCapabilityAdapter(pidfd bool) error {
	if activeScenario.world == nil {
		world, err := NewWorld(activeTest)
		if err != nil {
			return err
		}
		activeScenario.world = world
	}
	root := activeScenario.world.Root
	script := filepath.Join(root, "capability-provider")
	// The adapter reads the workspace inventory through `workspace list --json
	// --local`, so the double dispatches on that subcommand. Discovery and the
	// targeted revalidation both use it and both expect an items document; only
	// the stop invocation must answer with a receipt.
	content := "#!/bin/sh\nif [ \"$1 $2\" = \"workspace list\" ]; then printf '%s' '{\"items\":[{\"session_id\":\"provider-session\",\"process_generation\":\"g1\"}]}'\nelse printf '%s' '{\"signal_sent\":true,\"exit_confirmed\":false}'\nfi\n"
	if err := os.WriteFile(script, []byte(content), 0o700); err != nil {
		return err
	}
	probe := func() (topsailai.PlatformCapabilities, error) {
		return topsailai.PlatformCapabilities{ProcAvailable: true, PidfdAvailable: pidfd}, nil
	}
	a, err := topsailai.New(topsailai.Config{AdapterID: "bdd-adapter", Executable: script, PlatformProbe: probe, ResourceMapper: newCapabilityMapper()})
	if err != nil {
		return err
	}
	activeScenario.capabilityAdapter = a
	activeScenario.capabilityErr = nil
	activeScenario.capabilityCalls = 0
	return nil
}

func executeStop(generation string) error {
	if activeScenario.capabilityAdapter == nil {
		return errors.New("capability adapter is not configured")
	}
	result, err := activeScenario.capabilityAdapter.Discover(context.Background(), adapter.DiscoverRequest{})
	if err != nil {
		return err
	}
	if len(result.Sessions) != 1 {
		return fmt.Errorf("got %d discovered sessions", len(result.Sessions))
	}
	_, activeScenario.capabilityErr = activeScenario.capabilityAdapter.Execute(context.Background(), adapter.ExecuteRequest{Intent: protocol.ImmutableIntent{CommandID: "bdd-stop", Operation: "agent.stop", Target: &protocol.CommandTarget{ResourceID: result.Sessions[0].ClusterSessionID, ProviderGeneration: generation}}})
	return nil
}

func containsText(body []byte, text string) bool {
	for i := 0; i+len(text) <= len(body); i++ {
		if string(body[i:i+len(text)]) == text {
			return true
		}
	}
	return false
}
