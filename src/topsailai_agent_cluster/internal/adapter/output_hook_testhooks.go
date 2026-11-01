//go:build testhooks

package adapter

import "os"

func commandOutputUnsupported() bool {
	return os.Getenv("AGENT_CLUSTER_TEST_OUTPUT_UNSUPPORTED") == "1"
}
