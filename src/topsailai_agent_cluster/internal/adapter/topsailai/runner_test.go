package topsailai

import (
	"context"
	"os"
	"strings"
	"testing"
	"time"
)

func TestExecRunnerReturnsCommandOutputAndInput(t *testing.T) {
	runner := execRunner{timeout: 5 * time.Second}
	output, err := runner.Run(context.Background(), os.Args[0], []string{"-test.run=TestExecRunnerHelper", "--", "runner-input"}, []byte("input"))
	if err != nil {
		t.Fatal(err)
	}
	if string(output) != "runner-input:input" {
		t.Fatalf("output=%q", output)
	}
}

func TestExecRunnerReportsCommandFailure(t *testing.T) {
	runner := execRunner{timeout: time.Second}
	_, err := runner.Run(context.Background(), "definitely-not-a-real-provider-command", nil, nil)
	if err == nil || !strings.Contains(err.Error(), "run TopsailAI command") {
		t.Fatalf("error=%v", err)
	}
}

func TestExecRunnerReportsTimeout(t *testing.T) {
	runner := execRunner{timeout: time.Millisecond}
	_, err := runner.Run(context.Background(), os.Args[0], []string{"-test.run=TestExecRunnerHelper", "--", "runner-timeout"}, nil)
	if err == nil || !strings.Contains(err.Error(), "context deadline exceeded") {
		t.Fatalf("error=%v", err)
	}
}

func TestExecRunnerHelper(t *testing.T) {
	if len(os.Args) < 3 || os.Args[1] != "-test.run=TestExecRunnerHelper" {
		return
	}
	if len(os.Args) > 3 && os.Args[3] == "runner-timeout" {
		time.Sleep(time.Second)
		return
	}
	data := make([]byte, 32)
	n, _ := os.Stdin.Read(data)
	_, _ = os.Stdout.WriteString(os.Args[3] + ":" + string(data[:n]))
	os.Exit(0)
}
