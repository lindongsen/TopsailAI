package providerconformance

import (
	"bytes"
	"context"
	"strings"
	"testing"
	"time"
)

func TestBoundedBufferKeepsPrefixAndLabelsOverflow(t *testing.T) {
	buffer := newBoundedBuffer(4)
	if written, err := buffer.Write([]byte("abcdef")); err != nil || written != 6 {
		t.Fatalf("write=(%d,%v)", written, err)
	}
	if !bytes.Equal(buffer.Bytes(), []byte("abcd")) {
		t.Fatalf("content=%q", buffer.Bytes())
	}
	if !buffer.Exceeded() {
		t.Fatal("overflow was not recorded")
	}
}

func TestNewRunnerRejectsInvalidConfiguration(t *testing.T) {
	for _, config := range []Config{
		{},
		{Executable: "/provider"},
		{Executable: "/provider", Timeout: 1},
		{Executable: "/provider", Timeout: 1, MaxStdinBytes: 1, MaxStdoutBytes: 1, MaxStderrBytes: 1},
	} {
		if _, err := NewRunner(config); err == nil {
			t.Fatalf("invalid config accepted: %#v", config)
		}
	}
}

func TestInvokeDocumentRejectsOversizedStdinBeforeStartingProcess(t *testing.T) {
	runner, err := NewRunner(Config{
		Executable: "/does-not-exist", Timeout: time.Second, MaxStdinBytes: 3,
		MaxStdoutBytes: 1, MaxStderrBytes: 1, MaxRecords: 1,
	})
	if err != nil {
		t.Fatal(err)
	}
	_, err = runner.invokeDocument(context.Background(), []byte("four"))
	if err == nil || !strings.Contains(err.Error(), "stdin byte limit exceeded") {
		t.Fatalf("error=%v", err)
	}
}
