package main

import (
	"fmt"
	"sort"
	"strings"
)

// parsePairs reads a flat "key=value" list separated by commas.
//
// The shape is shared by every CLI configuration map because it has to survive one
// environment assignment, and because a nested format would need a parser the
// operator cannot read at a glance. One parser serves every map so the rules
// cannot drift: a second copy would eventually accept something the first one
// rejects, and the operator would see two different answers for one typo.
//
// Every malformed entry is rejected rather than skipped. A skipped entry would
// leave the operator believing a value was configured while the CLI silently used
// nothing, and the resulting failure would look like a problem on the far side
// instead of a typo in the local configuration.
//
// label names what one entry means, for example "name=url", so the error tells the
// operator the expected shape instead of only reporting that the shape was wrong.
//
// keyNoun and valueNoun name the two halves of one entry, for example "endpoint"
// and "token". They exist because a shared parser otherwise reports a generic
// "value" and "configures ... more than once", and the operator loses the word
// that says which half of the entry is wrong. Naming them per map keeps one
// implementation while keeping each map's message as precise as it was before the
// parser was shared.
//
// rejectSeparatorInValue is a per-map decision, not a general rule, because the
// two cases genuinely differ. A value containing "=" still parses unambiguously,
// since the split takes the first separator, so a base64 token with "=" padding or
// a URL with a query string is a legitimate value. The endpoint-token map rejects
// it anyway because that map is also written back by tooling, and a value holding
// the separator cannot be written back unambiguously. Applying that stricter rule
// everywhere would refuse a padded token for no reason; applying the looser rule
// everywhere would silently weaken the endpoint-token contract.
func parsePairs(value, envName, label, keyNoun, valueNoun string, rejectSeparatorInValue bool) (map[string]string, error) {
	pairs := make(map[string]string)
	trimmed := strings.TrimSpace(value)
	if trimmed == "" {
		return pairs, nil
	}
	for _, entry := range strings.Split(trimmed, ",") {
		pair := strings.TrimSpace(entry)
		if pair == "" {
			return nil, fmt.Errorf("%s contains an empty entry", envName)
		}
		key, item, found := strings.Cut(pair, "=")
		key = strings.TrimSpace(key)
		item = strings.TrimSpace(item)
		if !found || key == "" || item == "" {
			return nil, fmt.Errorf("%s entry %q is not a %s pair", envName, pair, label)
		}
		if rejectSeparatorInValue && strings.ContainsAny(item, ",=") {
			return nil, fmt.Errorf("%s entry %q has a %s containing a comma or equals sign", envName, key, valueNoun)
		}
		if _, duplicate := pairs[key]; duplicate {
			return nil, fmt.Errorf("%s configures %s %q more than once", envName, keyNoun, key)
		}
		pairs[key] = item
	}
	return pairs, nil
}

// sortedPairKeys returns the keys of a pair map in a stable order.
//
// A map iteration order is random, so an error that lists the configured names
// would name them in a different order on every run. An operator comparing two
// runs would then see a difference that is not a difference, and a test could not
// assert the message at all.
func sortedPairKeys(pairs map[string]string) []string {
	keys := make([]string, 0, len(pairs))
	for key := range pairs {
		keys = append(keys, key)
	}
	sort.Strings(keys)
	return keys
}
