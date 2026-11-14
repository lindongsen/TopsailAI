package protocol

import "strings"

// ClusterResourceIDPrefix begins every Cluster resource ID the Endpoint mints.
// It is the one place the prefix is spelled, so the minting side and the
// rejecting side cannot drift apart.
const ClusterResourceIDPrefix = "res_"

// clusterResourceIDHexLength is the number of lowercase hex characters the
// Endpoint appends to the prefix. randomResourceID encodes sixteen random bytes,
// so the suffix is always exactly this long.
const clusterResourceIDHexLength = 32

// IsClusterResourceID reports whether value has the shape of a Cluster resource
// ID the Endpoint mints.
//
// The shape is the only signal available to a provider CLI: the minting table
// lives in the Endpoint, so a provider process cannot ask whether a particular
// value was actually minted. Matching the shape is therefore the strictest check
// a provider can perform, and it is the check the contract requires, because a
// Cluster resource ID must never cross into provider authority.
func IsClusterResourceID(value string) bool {
	if !strings.HasPrefix(value, ClusterResourceIDPrefix) {
		return false
	}
	suffix := value[len(ClusterResourceIDPrefix):]
	if len(suffix) != clusterResourceIDHexLength {
		return false
	}
	for _, character := range suffix {
		isDigit := character >= '0' && character <= '9'
		isLowerHex := character >= 'a' && character <= 'f'
		if !isDigit && !isLowerHex {
			return false
		}
	}
	return true
}
