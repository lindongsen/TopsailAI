//go:build linux

package topsailai

import "testing"

func TestDefaultPlatformProbeReportsLinuxCapabilities(t *testing.T) {
	capabilities, err := defaultPlatformProbe()
	if err != nil {
		t.Fatal(err)
	}
	if !capabilities.ProcAvailable || !capabilities.PidfdAvailable {
		t.Fatalf("capabilities=%#v", capabilities)
	}
}
