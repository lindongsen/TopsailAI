package main

import (
	"io"
	"os"
	"testing"
	"time"

	"github.com/nats-io/nats-server/v2/server"
	"github.com/nats-io/nats.go"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

// captureOutput redirects stdout and stderr for the duration of fn and returns
// the captured bytes. It restores the original streams before returning.
func captureOutput(t *testing.T, fn func()) (stdout, stderr string) {
	t.Helper()

	oldOut := os.Stdout
	oldErr := os.Stderr
	defer func() {
		os.Stdout = oldOut
		os.Stderr = oldErr
	}()

	outR, outW, err := os.Pipe()
	require.NoError(t, err)
	os.Stdout = outW

	errR, errW, err := os.Pipe()
	require.NoError(t, err)
	os.Stderr = errW

	fn()

	outW.Close()
	errW.Close()

	outBytes, _ := io.ReadAll(outR)
	errBytes, _ := io.ReadAll(errR)

	return string(outBytes), string(errBytes)
}

// startEmbeddedNATSServer starts an embedded NATS server with JetStream enabled.
func startEmbeddedNATSServer(t *testing.T) *server.Server {
	t.Helper()

	opts := &server.Options{
		Port:      -1,
		JetStream: true,
		StoreDir:  t.TempDir(),
	}

	s, err := server.NewServer(opts)
	require.NoError(t, err)

	go s.Start()
	if !s.ReadyForConnections(5 * time.Second) {
		t.Fatal("NATS server did not start")
	}

	t.Cleanup(func() {
		s.Shutdown()
	})

	return s
}

// createStreamAndConsumer creates a JetStream stream and durable consumer on
// the embedded server and returns their names.
func createStreamAndConsumer(t *testing.T, srv *server.Server, stream, consumer string) {
	t.Helper()

	nc, err := nats.Connect(srv.ClientURL())
	require.NoError(t, err)
	defer nc.Close()

	js, err := nc.JetStream()
	require.NoError(t, err)

	_, err = js.AddStream(&nats.StreamConfig{
		Name:     stream,
		Subjects: []string{stream + ".>"},
	})
	require.NoError(t, err)

	_, err = js.AddConsumer(stream, &nats.ConsumerConfig{
		Durable:   consumer,
		AckPolicy: nats.AckExplicitPolicy,
	})
	require.NoError(t, err)
}

func TestRun_Version(t *testing.T) {
	stdout, _ := captureOutput(t, func() {
		err := run([]string{"--version"})
		require.NoError(t, err)
	})
	assert.Contains(t, stdout, "natsctl version")
	assert.Contains(t, stdout, version)
}

func TestRun_Help(t *testing.T) {
	t.Run("no args", func(t *testing.T) {
		stdout, _ := captureOutput(t, func() {
			err := run([]string{})
			require.NoError(t, err)
		})
		assert.Contains(t, stdout, "Usage: natsctl")
	})

	t.Run("--help", func(t *testing.T) {
		stdout, _ := captureOutput(t, func() {
			err := run([]string{"--help"})
			require.NoError(t, err)
		})
		assert.Contains(t, stdout, "Usage: natsctl")
	})

	t.Run("help command", func(t *testing.T) {
		stdout, _ := captureOutput(t, func() {
			err := run([]string{"help"})
			require.NoError(t, err)
		})
		assert.Contains(t, stdout, "Usage: natsctl")
	})
}

func TestRun_UnknownCommand(t *testing.T) {
	err := run([]string{"unknown"})
	require.Error(t, err)
	assert.Contains(t, err.Error(), "unknown command: unknown")
}

func TestRun_ConsumerHelp(t *testing.T) {
	t.Run("consumer with no subcommand", func(t *testing.T) {
		stdout, _ := captureOutput(t, func() {
			err := run([]string{"consumer"})
			require.Error(t, err)
			assert.Contains(t, err.Error(), "consumer subcommand required")
		})
		assert.Contains(t, stdout, "Usage: natsctl consumer")
	})

	t.Run("consumer help", func(t *testing.T) {
		stdout, _ := captureOutput(t, func() {
			err := run([]string{"consumer", "help"})
			require.NoError(t, err)
		})
		assert.Contains(t, stdout, "Usage: natsctl consumer")
	})
}

func TestRun_ConsumerRemove_MissingArgs(t *testing.T) {
	stdout, _ := captureOutput(t, func() {
		err := run([]string{"consumer", "rm"})
		require.Error(t, err)
		assert.Contains(t, err.Error(), "stream and consumer names are required")
	})
	assert.Contains(t, stdout, "Usage: natsctl consumer rm")
}

func TestRun_ConsumerRemove_DefaultNatsURL(t *testing.T) {
	// Ensure neither ACS_NATS_SERVERS nor NATS_URL is set so the default URL is used.
	t.Setenv("ACS_NATS_SERVERS", "")
	t.Setenv("NATS_URL", "")

	captureOutput(t, func() {
		err := run([]string{"consumer", "rm", "stream", "consumer", "-f"})
		require.Error(t, err)
	})
}

func TestRun_ConsumerRemove_ACSNATSServers(t *testing.T) {
	srv := startEmbeddedNATSServer(t)
	createStreamAndConsumer(t, srv, "acs-stream", "acs-consumer")
	t.Setenv("ACS_NATS_SERVERS", srv.ClientURL())
	t.Setenv("NATS_URL", "")

	stdout, _ := captureOutput(t, func() {
		err := run([]string{"consumer", "rm", "acs-stream", "acs-consumer", "-f"})
		require.NoError(t, err)
	})
	assert.Contains(t, stdout, "Consumer \"acs-consumer\" deleted from stream \"acs-stream\"")
}

func TestRun_ConsumerRemove_LegacyNATSURLFallback(t *testing.T) {
	srv := startEmbeddedNATSServer(t)
	createStreamAndConsumer(t, srv, "legacy-stream", "legacy-consumer")
	t.Setenv("ACS_NATS_SERVERS", "")
	t.Setenv("NATS_URL", srv.ClientURL())

	stdout, _ := captureOutput(t, func() {
		err := run([]string{"consumer", "rm", "legacy-stream", "legacy-consumer", "-f"})
		require.NoError(t, err)
	})
	assert.Contains(t, stdout, "Consumer \"legacy-consumer\" deleted from stream \"legacy-stream\"")
}

func TestRun_ConsumerRemove_ACSPrecedenceOverLegacy(t *testing.T) {
	srv := startEmbeddedNATSServer(t)
	createStreamAndConsumer(t, srv, "acs-stream", "acs-consumer")
	t.Setenv("ACS_NATS_SERVERS", srv.ClientURL())
	t.Setenv("NATS_URL", "nats://invalid:4222")

	stdout, _ := captureOutput(t, func() {
		err := run([]string{"consumer", "rm", "acs-stream", "acs-consumer", "-f"})
		require.NoError(t, err)
	})
	assert.Contains(t, stdout, "Consumer \"acs-consumer\" deleted from stream \"acs-stream\"")
}

func TestRun_ConsumerRemove_FlagOverridesEnv(t *testing.T) {
	srv := startEmbeddedNATSServer(t)
	createStreamAndConsumer(t, srv, "flag-stream", "flag-consumer")
	t.Setenv("ACS_NATS_SERVERS", "nats://invalid:4222")

	stdout, _ := captureOutput(t, func() {
		err := run([]string{"--nats-url", srv.ClientURL(), "consumer", "rm", "flag-stream", "flag-consumer", "-f"})
		require.NoError(t, err)
	})
	assert.Contains(t, stdout, "Consumer \"flag-consumer\" deleted from stream \"flag-stream\"")
}

func TestRun_ConsumerRemove_ConsumerNotFound(t *testing.T) {
	srv := startEmbeddedNATSServer(t)
	t.Setenv("ACS_NATS_SERVERS", srv.ClientURL())

	captureOutput(t, func() {
		err := run([]string{"consumer", "rm", "stream", "consumer", "-f"})
		require.Error(t, err)
		assert.Contains(t, err.Error(), "failed to delete consumer")
	})
}

func TestRun_ConsumerRemove_Success(t *testing.T) {
	srv := startEmbeddedNATSServer(t)
	t.Setenv("ACS_NATS_SERVERS", srv.ClientURL())
	createStreamAndConsumer(t, srv, "test-stream", "test-consumer")

	stdout, _ := captureOutput(t, func() {
		err := run([]string{"consumer", "rm", "test-stream", "test-consumer", "-f"})
		require.NoError(t, err)
	})
	assert.Contains(t, stdout, "Consumer \"test-consumer\" deleted from stream \"test-stream\"")
}

func TestRun_ConsumerRemove_Cancelled(t *testing.T) {
	srv := startEmbeddedNATSServer(t)
	t.Setenv("ACS_NATS_SERVERS", srv.ClientURL())

	// Provide "n" on stdin to cancel the operation.
	oldStdin := os.Stdin
	defer func() { os.Stdin = oldStdin }()
	r, w, err := os.Pipe()
	require.NoError(t, err)
	os.Stdin = r
	_, err = w.WriteString("n\n")
	require.NoError(t, err)
	w.Close()

	stdout, _ := captureOutput(t, func() {
		err := run([]string{"consumer", "rm", "stream", "consumer"})
		require.NoError(t, err)
	})
	assert.Contains(t, stdout, "Cancelled")
}

func TestRun_ConsumerRemove_Confirmed(t *testing.T) {
	srv := startEmbeddedNATSServer(t)
	t.Setenv("ACS_NATS_SERVERS", srv.ClientURL())
	createStreamAndConsumer(t, srv, "confirm-stream", "confirm-consumer")

	oldStdin := os.Stdin
	defer func() { os.Stdin = oldStdin }()
	r, w, err := os.Pipe()
	require.NoError(t, err)
	os.Stdin = r
	_, err = w.WriteString("y\n")
	require.NoError(t, err)
	w.Close()

	stdout, _ := captureOutput(t, func() {
		err := run([]string{"consumer", "rm", "confirm-stream", "confirm-consumer"})
		require.NoError(t, err)
	})
	assert.Contains(t, stdout, "Consumer \"confirm-consumer\" deleted from stream \"confirm-stream\"")
}

func TestGetACSEnv(t *testing.T) {
	t.Run("ACS value wins", func(t *testing.T) {
		t.Setenv("ACS_TEST_KEY", "acs-value")
		t.Setenv("LEGACY_TEST_KEY", "legacy-value")
		assert.Equal(t, "acs-value", getACSEnv("ACS_TEST_KEY", "LEGACY_TEST_KEY", "default"))
	})

	t.Run("legacy fallback", func(t *testing.T) {
		t.Setenv("ACS_TEST_KEY", "")
		t.Setenv("LEGACY_TEST_KEY", "legacy-value")
		assert.Equal(t, "legacy-value", getACSEnv("ACS_TEST_KEY", "LEGACY_TEST_KEY", "default"))
	})

	t.Run("default fallback", func(t *testing.T) {
		t.Setenv("ACS_TEST_KEY", "")
		t.Setenv("LEGACY_TEST_KEY", "")
		assert.Equal(t, "default", getACSEnv("ACS_TEST_KEY", "LEGACY_TEST_KEY", "default"))
	})

	t.Run("no legacy key uses default", func(t *testing.T) {
		t.Setenv("ACS_TEST_KEY", "")
		assert.Equal(t, "default", getACSEnv("ACS_TEST_KEY", "", "default"))
	})
}

func TestFlagArgs(t *testing.T) {
	// Register flags so flagArgs knows how to skip them.
	_ = flagString("nats-url", "", "")
	_ = flagBool("version", false, "")

	t.Run("keeps command and positional args", func(t *testing.T) {
		args := flagArgs([]string{"--nats-url", "nats://test", "consumer", "rm", "stream", "consumer", "-f"})
		assert.Equal(t, []string{"consumer", "rm", "stream", "consumer", "-f"}, args)
	})

	t.Run("preserves help flags", func(t *testing.T) {
		args := flagArgs([]string{"--nats-url", "nats://test", "consumer", "rm", "--help"})
		assert.Equal(t, []string{"consumer", "rm", "--help"}, args)
	})

	t.Run("handles --flag=value", func(t *testing.T) {
		args := flagArgs([]string{"--nats-url=nats://test", "consumer", "rm", "stream", "consumer"})
		assert.Equal(t, []string{"consumer", "rm", "stream", "consumer"}, args)
	})

	t.Run("handles bool flag", func(t *testing.T) {
		args := flagArgs([]string{"--version", "consumer", "rm", "stream", "consumer"})
		assert.Equal(t, []string{"consumer", "rm", "stream", "consumer"}, args)
	})
}

func TestFlagParse(t *testing.T) {
	t.Run("parses --flag value", func(t *testing.T) {
		p := flagString("nats-url", "default", "")
		flagParse([]string{"--nats-url", "nats://test", "consumer", "rm"})
		assert.Equal(t, "nats://test", *p)
	})

	t.Run("parses --flag=value", func(t *testing.T) {
		p := flagString("nats-url", "default", "")
		flagParse([]string{"--nats-url=nats://test", "consumer", "rm"})
		assert.Equal(t, "nats://test", *p)
	})

	t.Run("parses bool flag", func(t *testing.T) {
		p := flagBool("version", false, "")
		flagParse([]string{"--version", "consumer", "rm"})
		assert.True(t, *p)
	})

	t.Run("parses flags after positional args", func(t *testing.T) {
		p := flagString("nats-url", "default", "")
		flagParse([]string{"consumer", "rm", "--nats-url", "nats://test"})
		assert.Equal(t, "nats://test", *p)
	})
}

func TestHasHelpFlag(t *testing.T) {
	assert.True(t, hasHelpFlag([]string{"--help"}))
	assert.True(t, hasHelpFlag([]string{"-h"}))
	assert.True(t, hasHelpFlag([]string{"help"}))
	assert.False(t, hasHelpFlag([]string{"consumer", "rm", "--help"}))
	assert.False(t, hasHelpFlag([]string{"consumer", "rm"}))
}

func TestGetEnv(t *testing.T) {
	t.Setenv("TEST_GET_ENV_KEY", "value")
	assert.Equal(t, "value", getEnv("TEST_GET_ENV_KEY", "default"))

	t.Setenv("TEST_GET_ENV_KEY", "")
	assert.Equal(t, "default", getEnv("TEST_GET_ENV_KEY", "default"))
}
