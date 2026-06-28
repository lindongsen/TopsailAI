package main

import (
	"testing"
)

func TestNewAppFromConfigNoNATS(t *testing.T) {
	cfg := config{apiBase: "http://localhost:7370"}
	app, err := newAppFromConfig(cfg)
	if err != nil {
		t.Fatalf("unexpected error creating app: %v", err)
	}
	if app == nil {
		t.Fatal("expected app, got nil")
	}
	if app.nats != nil {
		t.Fatalf("expected app.nats to be nil when nats-url is empty, got %T %v", app.nats, app.nats)
	}
}

func TestNewAppFromConfigWithNATS(t *testing.T) {
	cfg := config{apiBase: "http://localhost:7370", natsURL: "nats://localhost:4222"}
	app, err := newAppFromConfig(cfg)
	if err != nil {
		t.Fatalf("unexpected error creating app: %v", err)
	}
	if app == nil {
		t.Fatal("expected app, got nil")
	}
	if app.nats == nil {
		t.Fatal("expected app.nats to be non-nil when nats-url is set")
	}
}

func TestNewAppFromConfigTypedNilRegression(t *testing.T) {
	// Regression test for the nil-interface panic: when nats-url is omitted,
	// app.nats must be a true nil interface, not a typed nil *NATSClient.
	cfg := config{apiBase: "http://localhost:7370"}
	app, err := newAppFromConfig(cfg)
	if err != nil {
		t.Fatalf("unexpected error creating app: %v", err)
	}
	if app.nats != nil {
		t.Fatalf("typed-nil regression: app.nats is non-nil interface holding %T", app.nats)
	}
}
