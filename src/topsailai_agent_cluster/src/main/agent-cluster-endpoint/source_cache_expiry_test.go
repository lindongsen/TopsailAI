package main

import (
	"testing"
	"time"
)

func TestSourceCacheExpiryDefaultsToTenMinutes(t *testing.T) {
	t.Setenv(sourceCacheExpiryEnvironment, "")
	expiry, err := sourceCacheExpiry()
	if err != nil || expiry != 10*time.Minute {
		t.Fatalf("expiry=%s error=%v, want 10m", expiry, err)
	}
}

func TestSourceCacheExpiryUsesEndpointEnvironment(t *testing.T) {
	t.Setenv(sourceCacheExpiryEnvironment, "17m")
	expiry, err := sourceCacheExpiry()
	if err != nil || expiry != 17*time.Minute {
		t.Fatalf("expiry=%s error=%v, want 17m", expiry, err)
	}
}

func TestSourceCacheExpiryRejectsInvalidValues(t *testing.T) {
	for _, value := range []string{"invalid", "0", "-1m"} {
		t.Run(value, func(t *testing.T) {
			t.Setenv(sourceCacheExpiryEnvironment, value)
			if _, err := sourceCacheExpiry(); err == nil {
				t.Fatalf("value %q was accepted", value)
			}
		})
	}
}
