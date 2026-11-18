package main

import (
	"fmt"
	"os"
	"time"
)

const commandJournalExpiryEnvironment = "AGENT_CLUSTER_ENDPOINT_COMMAND_JOURNAL_EXPIRY"

// commandJournalExpiry reads the Endpoint-owned command journal retention at the
// process boundary. Invalid and non-positive values fail startup so a typo cannot
// silently disable cleanup, exactly as source cache retention already behaves.
//
// The default is 720h (30 days). A settled receipt is history rather than live
// state, so a month is long enough to investigate a recent incident while still
// bounding the table: at the measured rate of about 86 rows and 130 KB per day,
// 30 days holds roughly 2,600 rows and 4 MB.
func commandJournalExpiry() (time.Duration, error) {
	const fallback = 720 * time.Hour
	value := os.Getenv(commandJournalExpiryEnvironment)
	if value == "" {
		return fallback, nil
	}
	expiry, err := time.ParseDuration(value)
	if err != nil {
		return 0, fmt.Errorf("parse %s: %w", commandJournalExpiryEnvironment, err)
	}
	if expiry <= 0 {
		return 0, fmt.Errorf("%s must be positive", commandJournalExpiryEnvironment)
	}
	return expiry, nil
}
