package adapter

import (
	"context"
	"testing"
)

type testAdapter struct{}

func (testAdapter) Describe(context.Context) (Descriptor, error) { return Descriptor{}, nil }
func (testAdapter) Discover(context.Context, DiscoverRequest) (DiscoverResult, error) {
	return DiscoverResult{}, nil
}
func (testAdapter) Inspect(context.Context, InspectRequest) (InspectResult, error) {
	return InspectResult{}, nil
}
func (testAdapter) Execute(context.Context, ExecuteRequest) (ExecuteResult, error) {
	return ExecuteResult{}, nil
}
func (testAdapter) ReadOutput(context.Context, OutputRequest) (OutputResult, error) {
	return OutputResult{}, nil
}
func (testAdapter) QueryCommand(context.Context, CommandQuery) (CommandResult, error) {
	return CommandResult{}, ErrUnsupported
}
func (testAdapter) Watch(context.Context) (<-chan Event, error) { return nil, ErrUnsupported }
func (testAdapter) Close() error                                { return nil }

func TestRegistrySupportsMultipleInstancesAndRejectsDuplicates(t *testing.T) {
	r := NewRegistry()
	if err := r.RegisterType("fixture", func(context.Context, Config) (Adapter, error) { return testAdapter{}, nil }); err != nil {
		t.Fatal(err)
	}
	if err := r.RegisterType("fixture", func(context.Context, Config) (Adapter, error) { return testAdapter{}, nil }); err == nil {
		t.Fatal("expected duplicate type error")
	}
	if _, err := r.Configure(context.Background(), Config{AdapterID: "a", ProviderType: "fixture"}); err != nil {
		t.Fatal(err)
	}
	if _, err := r.Configure(context.Background(), Config{AdapterID: "b", ProviderType: "fixture"}); err != nil {
		t.Fatal(err)
	}
	if _, ok := r.Get("a"); !ok {
		t.Fatal("adapter a not found")
	}
	if _, err := r.Configure(context.Background(), Config{AdapterID: "a", ProviderType: "fixture"}); err == nil {
		t.Fatal("expected duplicate instance error")
	}
}
