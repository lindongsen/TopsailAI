package endpoint

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"testing"

	"topsailai_agent_cluster/internal/adapter"
	"topsailai_agent_cluster/internal/protocol"
)

type projectAdapter struct {
	timeoutAdapter
	fail error
}

// ProjectCatalog supplies read-only project evidence for executor routing.
func (a projectAdapter) ProjectCatalog(context.Context, protocol.ProjectCatalogQuery) (protocol.ProjectCatalog, error) {
	if a.fail != nil {
		return protocol.ProjectCatalog{}, a.fail
	}
	return protocol.ProjectCatalog{Projects: []protocol.Project{{ProjectID: "pr-1", Name: "one", Path: "/work/one"}}, ObservedAtMS: 1}, nil
}

// TestExecutorProjectCatalog validates live catalog and provider failure.
func TestExecutorProjectCatalog(t *testing.T) {
	for _, failure := range []error{nil, errors.New("provider unavailable")} {
		registry := adapter.NewRegistry()
		registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) {
			return projectAdapter{fail: failure}, nil
		})
		registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
		e := &Executor{registry: registry}
		result, err := e.ProjectCatalog(context.Background(), protocol.ProjectCatalogQuery{})
		if (err != nil) != (failure != nil) || (failure == nil && len(result.Projects) != 1) {
			t.Fatalf("%#v %v", result, err)
		}
	}
}

// TestExecutorProjectCatalogBusyIsNotProviderFailure proves capacity is classified separately.
func TestExecutorProjectCatalogBusyIsNotProviderFailure(t *testing.T) {
	registry := adapter.NewRegistry()
	registry.RegisterType("test", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return projectAdapter{fail: fmt.Errorf("%w: discovery", adapter.ErrBusy)}, nil
	})
	registry.Configure(context.Background(), adapter.Config{AdapterID: "a1", ProviderType: "test"})
	e := &Executor{registry: registry}
	result, err := e.ProjectCatalog(context.Background(), protocol.ProjectCatalogQuery{})
	if !errors.Is(err, adapter.ErrBusy) || result.ErrorCode != protocol.AdapterBusy {
		t.Fatalf("result=%#v err=%v", result, err)
	}
}

// TestExecutorProjectCatalogSkipsUnsupportedAdaptersAndSorts proves one incapable
// Adapter cannot hide a later capable Adapter and output order is deterministic.
func TestExecutorProjectCatalogSkipsUnsupportedAdaptersAndSorts(t *testing.T) {
	registry := adapter.NewRegistry()
	registry.RegisterType("unsupported", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return projectAdapter{fail: adapter.ErrUnsupported}, nil
	})
	registry.RegisterType("supported", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return projectPairAdapter{}, nil
	})
	registry.Configure(context.Background(), adapter.Config{AdapterID: "first", ProviderType: "unsupported"})
	registry.Configure(context.Background(), adapter.Config{AdapterID: "second", ProviderType: "supported"})
	result, err := (&Executor{registry: registry}).ProjectCatalog(context.Background(), protocol.ProjectCatalogQuery{})
	if err != nil || len(result.Projects) != 2 {
		t.Fatalf("result=%#v err=%v", result, err)
	}
	if result.Projects[0].Name != "a" || result.Projects[1].Name != "z" {
		t.Fatalf("projects are not sorted: %#v", result.Projects)
	}
}

type projectPairAdapter struct{ timeoutAdapter }

func (projectPairAdapter) ProjectCatalog(context.Context, protocol.ProjectCatalogQuery) (protocol.ProjectCatalog, error) {
	return protocol.ProjectCatalog{Projects: []protocol.Project{{ProjectID: "z", Name: "z", Path: "/z"}, {ProjectID: "a", Name: "a", Path: "/a"}}, ObservedAtMS: 2}, nil
}

type boundedProjectAdapter struct {
	timeoutAdapter
	count int
}

func (a boundedProjectAdapter) ProjectCatalog(context.Context, protocol.ProjectCatalogQuery) (protocol.ProjectCatalog, error) {
	projects := make([]protocol.Project, a.count)
	for index := range projects {
		projects[index] = protocol.Project{ProjectID: fmt.Sprintf("pr-%d", index), Name: fmt.Sprintf("project-%d", index), Path: fmt.Sprintf("/work/%d", index)}
	}
	return protocol.ProjectCatalog{Projects: projects, ObservedAtMS: 1}, nil
}

// TestExecutorProjectCatalogRejectsCombinedAdapterOverflow proves the public
// catalog bound applies after Adapter aggregation, not only to each Provider.
func TestExecutorProjectCatalogRejectsCombinedAdapterOverflow(t *testing.T) {
	registry := adapter.NewRegistry()
	registry.RegisterType("bounded", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return boundedProjectAdapter{count: protocol.MaxProjects/2 + 1}, nil
	})
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "first", ProviderType: "bounded"}); err != nil {
		t.Fatal(err)
	}
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "second", ProviderType: "bounded"}); err != nil {
		t.Fatal(err)
	}
	result, err := (&Executor{registry: registry}).ProjectCatalog(context.Background(), protocol.ProjectCatalogQuery{})
	if err == nil || result.ErrorCode != protocol.ProjectCatalogTooLarge || len(result.Projects) != 0 {
		t.Fatalf("result=%#v err=%v", result, err)
	}
}

// TestExecutorProjectCatalogRejectsCombinedByteOverflow proves the public byte
// bound applies after Adapter aggregation and Cluster ID mapping.
func TestExecutorProjectCatalogRejectsCombinedByteOverflow(t *testing.T) {
	registry := adapter.NewRegistry()
	registry.RegisterType("wide", func(context.Context, adapter.Config) (adapter.Adapter, error) {
		return projectAdapterWithCatalog{catalog: protocol.ProjectCatalog{Projects: []protocol.Project{{ProjectID: "pr-wide", Name: "wide", Path: "/" + strings.Repeat("x", protocol.MaxProjectBytes)}}, ObservedAtMS: 1}}, nil
	})
	if _, err := registry.Configure(context.Background(), adapter.Config{AdapterID: "wide", ProviderType: "wide"}); err != nil {
		t.Fatal(err)
	}
	result, err := (&Executor{registry: registry}).ProjectCatalog(context.Background(), protocol.ProjectCatalogQuery{})
	if err == nil || result.ErrorCode != protocol.ProjectCatalogTooLarge || len(result.Projects) != 0 {
		t.Fatalf("result=%#v err=%v", result, err)
	}
}

type projectAdapterWithCatalog struct {
	timeoutAdapter
	catalog protocol.ProjectCatalog
}

func (a projectAdapterWithCatalog) ProjectCatalog(context.Context, protocol.ProjectCatalogQuery) (protocol.ProjectCatalog, error) {
	return a.catalog, nil
}
