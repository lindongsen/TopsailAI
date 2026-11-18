//go:build linux

package main

import "testing"

// TestProbePlatformCapabilitiesReportsLinuxSupport proves the probe really opens a
// pidfd rather than assuming one.
//
// The probe is the only evidence the descriptor has, so a probe that returned a
// constant would make the gate vacuous: the capability would be advertised on every
// Linux host whether or not the call works.
func TestProbePlatformCapabilitiesReportsLinuxSupport(t *testing.T) {
	capabilities := probePlatformCapabilities()
	if !capabilities.ProcAvailable {
		t.Fatal("the process table is not reported as readable on Linux")
	}
	if !capabilities.PidfdAvailable {
		t.Fatal("pidfd_open is not reported as available on Linux")
	}
	if !capabilities.stopSupported() {
		t.Fatal("stop is not supported on a host that reports both capabilities")
	}
}

// TestPidfdProbeRejectsAnImpossibleSyscallNumber proves the probe really calls the
// kernel instead of returning a constant.
//
// Zero is not a valid syscall number, so the call must fail. A probe that ignored its
// argument would report success here and would therefore report support on a host that
// cannot open a pidfd at all.
func TestPidfdProbeRejectsAnImpossibleSyscallNumber(t *testing.T) {
	if pidfdAvailable(0) {
		t.Fatal("an impossible syscall number is reported as opening a pidfd")
	}
	if !pidfdAvailable(sysPidfdOpen) {
		t.Fatal("the declared pidfd_open number does not open a pidfd")
	}
}

// TestStopSupportedRequiresOnlyTheProcessTable proves the gate describes
// reachability rather than the strongest available binding.
//
// A readable process table is enough, because the provider CLI re-verifies the
// process identity immediately before signalling when the pidfd bindings are
// absent. A pidfd without a readable process table is still not enough, because
// the target identity cannot be verified at all. Requiring the pidfd here would
// hide an operation the deployment can serve, which is the defect this gate had.
func TestStopSupportedRequiresOnlyTheProcessTable(t *testing.T) {
	sufficient := map[string]platformCapabilities{
		"process table only": {ProcAvailable: true},
		"process table and pidfd": {
			ProcAvailable:  true,
			PidfdAvailable: true,
		},
	}
	for name, capabilities := range sufficient {
		t.Run(name, func(t *testing.T) {
			if !capabilities.stopSupported() {
				t.Fatalf("capabilities=%#v are reported as insufficient", capabilities)
			}
		})
	}

	insufficient := map[string]platformCapabilities{
		"neither":    {},
		"pidfd only": {PidfdAvailable: true},
	}
	for name, capabilities := range insufficient {
		t.Run(name, func(t *testing.T) {
			if capabilities.stopSupported() {
				t.Fatalf("capabilities=%#v are reported as sufficient", capabilities)
			}
		})
	}
}
