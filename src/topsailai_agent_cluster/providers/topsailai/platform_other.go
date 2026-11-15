//go:build !linux

package main

// platformCapabilities reports the host support agent.stop requires.
type platformCapabilities struct {
	ProcAvailable  bool
	PidfdAvailable bool
}

// stopSupported reports no support where the probe cannot run.
//
// A platform without the probe is not assumed to support the operation: the
// descriptor must not advertise a capability this executable cannot honour.
func (c platformCapabilities) stopSupported() bool {
	return false
}

// probePlatformCapabilities reports no support on this platform.
func probePlatformCapabilities() platformCapabilities {
	return platformCapabilities{}
}
