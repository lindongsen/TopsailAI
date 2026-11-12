package providercli

import "fmt"

// NegotiateVersion selects the highest Provider CLI version supported by both
// the Endpoint contract and one Provider descriptor.
func NegotiateVersion(provider ProtocolRange) (Version, error) {
	if err := provider.validate(); err != nil {
		return Version{}, err
	}
	if provider.Major != ProtocolMajor {
		return Version{}, fmt.Errorf("incompatible provider protocol major %d", provider.Major)
	}
	minor := ProtocolMinor
	if provider.Maximum < minor {
		minor = provider.Maximum
	}
	if minor < provider.Minimum {
		return Version{}, fmt.Errorf(
			"no common provider protocol minor: endpoint maximum %d, provider range %d-%d",
			ProtocolMinor,
			provider.Minimum,
			provider.Maximum,
		)
	}
	return Version{Protocol: ProtocolName, Major: ProtocolMajor, Minor: minor}, nil
}

// ValidateResponseCorrelation verifies that a non-streaming response belongs to
// the request and uses the version selected for that invocation.
func ValidateResponseCorrelation(request Request, response Response) error {
	if request.RequestID != response.RequestID {
		return fmt.Errorf("provider response request_id %q does not match %q", response.RequestID, request.RequestID)
	}
	if request.Version != response.Version {
		return fmt.Errorf(
			"provider response version %s/%d.%d does not match request %s/%d.%d",
			response.Protocol,
			response.Major,
			response.Minor,
			request.Protocol,
			request.Major,
			request.Minor,
		)
	}
	return nil
}
