package main

import (
	"fmt"
	"os"
	"time"
)

const sourceCacheExpiryEnvironment = "AGENT_CLUSTER_ENDPOINT_SOURCE_CACHE_EXPIRY"

// sourceCacheExpiry reads the Endpoint-owned cache retention at the process
// boundary. Invalid and non-positive values fail startup so a typo cannot
// silently disable cleanup.
func sourceCacheExpiry() (time.Duration, error) {
	const fallback = 10 * time.Minute
	value := os.Getenv(sourceCacheExpiryEnvironment)
	if value == "" {
		return fallback, nil
	}
	expiry, err := time.ParseDuration(value)
	if err != nil {
		return 0, fmt.Errorf("parse %s: %w", sourceCacheExpiryEnvironment, err)
	}
	if expiry <= 0 {
		return 0, fmt.Errorf("%s must be positive", sourceCacheExpiryEnvironment)
	}
	return expiry, nil
}
