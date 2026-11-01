// Command provider-fixture emits controlled adapter test data.
package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strings"
	"time"
)

type response struct {
	Sessions []map[string]string `json:"sessions"`
	Complete bool                `json:"complete"`
}

func main() {
	mode := flag.String("mode", "success", "fixture response mode")
	executeID := flag.String("execute-command-id", "", "command identifier for execution")
	operation := flag.String("operation", "", "operation being executed")
	readOutput := flag.String("read-output", "", "resource whose output is requested")
	targetResourceID := flag.String("target-resource-id", "", "provider resource target")
	targetGeneration := flag.String("target-generation", "", "resource generation target")
	payload := flag.String("payload", "", "JSON command payload")
	maxBytes := flag.Int("max-bytes", 0, "maximum output bytes")
	outputSize := flag.Int("output-size", 0, "provider output size for snapshot tests")
	failExecution := flag.Bool("fail-execution", false, "fail command execution while keeping discovery available")
	recordFile := flag.String("record-file", "", "append execution evidence to this file")
	delayMS := flag.Int("delay-ms", 0, "delay execution for evidence tests")
	discoveryCountFile := flag.String("discovery-count-file", "", "durable discovery invocation counter")
	failAfterN := flag.Int("fail-after-n", -1, "fail discovery after N successful calls; zero fails immediately")
	alwaysFail := flag.Bool("always-fail", false, "fail every discovery call")
	flag.Parse()
	if *readOutput != "" {
		data := "provider output marker"
		truncated := false
		if *maxBytes > 0 && len(data) > *maxBytes {
			data = data[:*maxBytes]
			truncated = true
		}
		if *outputSize > len(data) {
			data += strings.Repeat("x", *outputSize-len(data))
		}
		_ = json.NewEncoder(os.Stdout).Encode(map[string]any{"data": data, "truncated": truncated})
		return
	}
	if *executeID == "" {
		count := 1
		if *discoveryCountFile != "" {
			if data, err := os.ReadFile(*discoveryCountFile); err == nil {
				_, _ = fmt.Sscanf(string(data), "%d", &count)
				count++
			}
			_ = os.WriteFile(*discoveryCountFile, []byte(fmt.Sprint(count)), 0o600)
		}
		threshold, configured := configuredFailureThreshold(*failAfterN)
		if !configured {
			if limit := os.Getenv("AGENT_CLUSTER_TEST_PROVIDER_FAIL_AFTER_N"); limit != "" {
				var err error
				threshold, err = parseThreshold(limit)
				configured = err == nil
			}
		}
		if *alwaysFail || (configured && count > threshold) {
			data := map[string]any{"error": "fixture_discovery_failed", "call": count, "fail_after_n": threshold}
			_ = json.NewEncoder(os.Stderr).Encode(data)
			os.Exit(2)
		}
	}
	if *executeID != "" {
		if *failExecution {
			fmt.Fprintln(os.Stderr, "fixture execution failure")
			os.Exit(2)
		}
		startNS := time.Now().UnixNano()
		if *delayMS > 0 {
			time.Sleep(time.Duration(*delayMS) * time.Millisecond)
		}
		if logPath := os.Getenv("AGENT_CLUSTER_TEST_PROVIDER_INVOCATION_LOG"); logPath != "" {
			*recordFile = logPath
		}
		if *recordFile != "" {
			file, err := os.OpenFile(*recordFile, os.O_CREATE|os.O_APPEND|os.O_WRONLY, 0o600)
			if err != nil {
				fmt.Fprintln(os.Stderr, err)
				os.Exit(3)
			}
			endNS := time.Now().UnixNano()
			record := map[string]any{"command_id": *executeID, "operation": *operation, "timestamp_ns": endNS, "start_ns": startNS, "end_ns": endNS, "pid": os.Getpid(), "target_resource_id": *targetResourceID, "target_generation": *targetGeneration, "payload": *payload}
			if err := json.NewEncoder(file).Encode(record); err != nil {
				_ = file.Close()
				fmt.Fprintln(os.Stderr, err)
				os.Exit(3)
			}
			_ = file.Close()
		}
		if os.Getenv("AGENT_CLUSTER_TEST_CRASH_AFTER_INVOCATION_STARTED") == "1" {
			os.Exit(97)
		}
		if *operation == "agent.stop" || containsArgument("kill") {
			result := map[string]any{"command_id": *executeID, "delivery_boundary": "signal_sent", "signal_sent": true, "exit_confirmed": false}
			_ = json.NewEncoder(os.Stdout).Encode(result)
			return
		}
		result := map[string]any{"command_id": *executeID, "outcome": "accepted", "effect_certainty": "acknowledged", "delivery_boundary": "submitted"}
		_ = json.NewEncoder(os.Stdout).Encode(result)
		return
	}
	if *mode == "fail" {
		fmt.Fprintln(os.Stderr, "fixture failure")
		os.Exit(2)
	}
	result := response{Complete: true}
	if *mode == "one" {
		result.Sessions = []map[string]string{{"session_id": "fixture-session", "generation": "fixture-generation", "state": "idle", "agent_id": "fixture-agent"}}
	}
	_ = json.NewEncoder(os.Stdout).Encode(result)
}

func configuredFailureThreshold(value int) (int, bool) {
	return value, value >= 0
}

func parseThreshold(value string) (int, error) {
	var threshold int
	_, err := fmt.Sscanf(value, "%d", &threshold)
	if err != nil || threshold < 0 {
		return 0, fmt.Errorf("invalid failure threshold %q", value)
	}
	return threshold, nil
}

func containsArgument(want string) bool {
	for _, argument := range os.Args[1:] {
		if argument == want {
			return true
		}
	}
	return false
}
