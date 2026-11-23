package main

import (
	"encoding/json"
	"strings"
	"testing"
)

// TestWarningsSerializeIntoTheResponseDocument proves the warning reaches the wire
// document, not only the Go struct.
//
// The Cluster decoder is strict, so a field that exists in the struct but is
// omitted from the document would make the warning invisible to every consumer
// while every unit test on the struct still passed. The empty case is asserted in
// the same test because `omitempty` is what keeps a warning-free result
// byte-identical to the previous release.
func TestWarningsSerializeIntoTheResponseDocument(t *testing.T) {
	warning := "hard_interrupt carries no message, so the supplied message was not delivered"
	doc, err := json.Marshal(operationResult{
		DeliveryBoundary: "submitted",
		EffectCertainty:  "acknowledged",
		ProviderOutcome:  "submitted",
		Warnings:         []string{warning},
	})
	if err != nil {
		t.Fatal(err)
	}
	if !strings.Contains(string(doc), `"warnings":["`+warning+`"]`) {
		t.Fatalf("warnings missing from the wire document: %s", doc)
	}

	empty, err := json.Marshal(operationResult{DeliveryBoundary: "submitted"})
	if err != nil {
		t.Fatal(err)
	}
	if strings.Contains(string(empty), "warnings") {
		t.Fatalf("a result without warnings must omit the field: %s", empty)
	}
}
