//go:build !linux

package topsailai

func defaultPlatformProbe() (PlatformCapabilities, error) {
	return PlatformCapabilities{}, nil
}
