package main

import (
	"encoding/json"
	"os"
	"testing"
)

// TestWatchIsAdmittedByTheProtocolButNotServedByTheMock pins the three facts
// that together explain why functionWatch exists and is never dispatched.
//
// The facts are pinned together on purpose. Any one of them alone is misleading:
// the constant alone looks like dead code, the absence from the advertised list
// alone looks like an oversight, and the schema entry alone says nothing about
// this mock. Only the combination records that the mock is silent by choice.
func TestWatchIsAdmittedByTheProtocolButNotServedByTheMock(t *testing.T) {
	t.Run("the protocol admits the name", func(t *testing.T) {
		path := clusterPath(t, "protocol", "provider-cli", "v1", "request.schema.json")
		data, err := os.ReadFile(path)
		if err != nil {
			t.Fatalf("read request schema: %v", err)
		}
		var schema struct {
			Properties struct {
				Function struct {
					Enum []string `json:"enum"`
				} `json:"function"`
			} `json:"properties"`
		}
		if err := json.Unmarshal(data, &schema); err != nil {
			t.Fatalf("decode request schema: %v", err)
		}
		found := false
		for _, name := range schema.Properties.Function.Enum {
			if name == functionWatch {
				found = true
			}
		}
		if !found {
			t.Fatalf("request schema function enum = %#v, want it to admit %q",
				schema.Properties.Function.Enum, functionWatch)
		}
	})

	t.Run("the mock does not advertise it", func(t *testing.T) {
		descriptor := mockDescriptor("")
		for _, name := range descriptor.Functions {
			if name == functionWatch {
				t.Fatalf("functions = %#v, want %q absent because the mock never serves it",
					descriptor.Functions, functionWatch)
			}
		}
	})

	t.Run("the mock does not dispatch it", func(t *testing.T) {
		response := handleUnary(request{
			RequestID: "req-watch",
			Function:  functionWatch,
		}, "", mockOptions{})
		if response.Error == nil {
			t.Fatalf("watch response = %#v, want an error because the mock never serves it", response)
		}
		if response.Error.Code != "unsupported" {
			t.Fatalf("watch error code = %q, want %q", response.Error.Code, "unsupported")
		}
	})
}
