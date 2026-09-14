"""Unit tests for automatic ffplay output selection in input_bell."""

import os
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock

from topsailai.scripts import input_bell

class TestInputBellAudioDetection(TestCase):
    """Verify ffplay output probing and explicit-command behavior."""

    def setUp(self):
        """Clear the process-local probe cache between tests."""
        input_bell._AUTO_SOUND_COMMAND = None

    def tearDown(self):
        """Leave the module cache empty for unrelated tests."""
        input_bell._AUTO_SOUND_COMMAND = None

    def test_sound_candidates_try_default_before_discovered_hardware(self):
        """Default routing remains preferred over direct ALSA hardware."""
        with mock.patch.object(input_bell, "_pulseaudio_sessions", return_value=[]), mock.patch.object(
            input_bell,
            "_alsa_playback_devices",
            return_value=["plughw:0,0", "plughw:1,3", "plughw:0,0"],
        ):
            candidates = input_bell._sound_candidates()

        self.assertEqual(candidates[0], (input_bell.DEFAULT_SOUND_CMD, None, None))
        self.assertEqual(
            candidates[1:],
            [
                (
                    input_bell.DEFAULT_SOUND_CMD,
                    {"SDL_AUDIODRIVER": "alsa", "AUDIODEV": "plughw:0,0"},
                    None,
                ),
                (
                    input_bell.DEFAULT_SOUND_CMD,
                    {"SDL_AUDIODRIVER": "alsa", "AUDIODEV": "plughw:1,3"},
                    None,
                ),
            ],
        )

    def test_sound_candidates_prefer_discovered_pulseaudio_session(self):
        """An active desktop PulseAudio server is tried before root audio routes."""
        session = ("unix:/tmp/pulse-session/native", "desktop", "/home/desktop")
        with mock.patch.object(input_bell, "_pulseaudio_sessions", return_value=[session]), mock.patch.object(
            input_bell, "_alsa_playback_devices", return_value=[]
        ):
            candidates = input_bell._sound_candidates()

        self.assertEqual(
            candidates,
            [
                (
                    input_bell.DEFAULT_SOUND_CMD,
                    {
                        "HOME": "/home/desktop",
                        "PULSE_SERVER": "unix:/tmp/pulse-session/native",
                        "SDL_AUDIODRIVER": "pulseaudio",
                    },
                    "desktop",
                ),
                (input_bell.DEFAULT_SOUND_CMD, None, None),
            ],
        )

    def test_sound_command_switches_to_discovered_session_user_as_root(self):
        """Root invokes ffplay as the owner of the active desktop audio session."""
        result = SimpleNamespace(returncode=0, stderr="")
        account = SimpleNamespace(pw_uid=1000)
        with mock.patch.object(input_bell.os, "geteuid", return_value=0), mock.patch(
            "pwd.getpwnam", return_value=account
        ), mock.patch.object(input_bell.subprocess, "run", return_value=result) as run:
            self.assertTrue(
                input_bell._run_sound_command(
                    "ffplay -tone",
                    {"PULSE_SERVER": "unix:/tmp/pulse-session/native"},
                    "desktop",
                )
            )

        self.assertEqual(
            run.call_args.args[0],
            ["runuser", "-u", "desktop", "--", "ffplay", "-tone"],
        )
        self.assertEqual(
            run.call_args.kwargs["env"]["PULSE_SERVER"],
            "unix:/tmp/pulse-session/native",
        )

    def test_sound_command_uses_session_directly_for_its_owner(self):
        """The desktop user does not need a privileged user switch."""
        result = SimpleNamespace(returncode=0, stderr="")
        account = SimpleNamespace(pw_uid=1000)
        with mock.patch.object(input_bell.os, "geteuid", return_value=1000), mock.patch(
            "pwd.getpwnam", return_value=account
        ), mock.patch.object(input_bell.subprocess, "run", return_value=result) as run:
            self.assertTrue(
                input_bell._run_sound_command(
                    "ffplay -tone",
                    {"PULSE_SERVER": "unix:/tmp/pulse-session/native"},
                    "desktop",
                )
            )

        self.assertEqual(run.call_args.args[0], ["ffplay", "-tone"])

    def test_alsa_playback_devices_reads_unique_hardware_outputs(self):
        """Only ALSA playback entries become direct ffplay candidates."""
        pcm_file = Path(self._tmpdir()) / "pcm"
        pcm_file.write_text(
            "00-00: Analog : Analog : playback 1 : capture 1\n"
            "00-03: HDMI 0 : HDMI 0 : playback 1\n"
            "00-00: Analog : Analog : playback 1 : capture 1\n"
            "01-00: Capture : Capture : capture 1\n",
            encoding="utf-8",
        )

        self.assertEqual(
            input_bell._alsa_playback_devices(pcm_file),
            ["plughw:0,0", "plughw:0,3"],
        )

    def test_automatic_probe_selects_and_caches_first_successful_command(self):
        """A selected ffplay route is reused without probing again."""
        candidates = [
            (input_bell.DEFAULT_SOUND_CMD, None, None),
            (
                input_bell.DEFAULT_SOUND_CMD,
                {"AUDIODEV": "plughw:0,0"},
                None,
            ),
        ]
        with mock.patch.object(input_bell, "_sound_candidates", return_value=candidates), mock.patch.object(
            input_bell, "_run_sound_command", side_effect=[False, True, True]
        ) as run:
            self.assertTrue(input_bell._ring_bell(None))
            self.assertTrue(input_bell._ring_bell(None))

        self.assertEqual(run.call_count, 3)
        self.assertEqual(run.call_args_list[0].args, candidates[0])
        self.assertEqual(run.call_args_list[1].args, candidates[1])
        self.assertEqual(run.call_args_list[2].args, candidates[1])

    def test_automatic_probe_returns_false_when_no_output_works(self):
        """All failed candidates leave no unusable route cached."""
        candidates = [(input_bell.DEFAULT_SOUND_CMD, None, None)]
        with mock.patch.object(input_bell, "_sound_candidates", return_value=candidates), mock.patch.object(
            input_bell, "_run_sound_command", return_value=False
        ):
            self.assertFalse(input_bell._ring_bell(None))

        self.assertIsNone(input_bell._AUTO_SOUND_COMMAND)

    def test_explicit_sound_command_bypasses_automatic_probe(self):
        """User-configured playback commands retain full precedence."""
        with mock.patch.object(input_bell, "_sound_candidates") as candidates, mock.patch.object(
            input_bell, "_run_sound_command", return_value=True
        ) as run:
            self.assertTrue(input_bell._ring_bell("ffplay -custom"))

        candidates.assert_not_called()
        run.assert_called_once_with("ffplay -custom", None)

    def test_sound_command_rejects_ffplay_audio_failure_reported_with_zero_exit(self):
        """ffplay diagnostics override its misleading successful process exit."""
        result = SimpleNamespace(
            returncode=0,
            stderr="ALSA: Couldn't open audio device: Host is down\naudio open failed",
        )
        with mock.patch.object(input_bell.subprocess, "run", return_value=result):
            self.assertFalse(input_bell._run_sound_command("ffplay -tone", None))

    def test_sound_command_accepts_clean_successful_ffplay_run(self):
        """A clean ffplay completion remains a valid playback route."""
        result = SimpleNamespace(returncode=0, stderr="")
        with mock.patch.object(input_bell.subprocess, "run", return_value=result):
            self.assertTrue(input_bell._run_sound_command("ffplay -tone", None))

    def test_run_once_reports_detected_and_played_when_bell_succeeds(self):
        """A successful cycle reports both INPUT detection and playback."""
        with mock.patch.object(
            input_bell, "_has_input_sessions", return_value=True
        ), mock.patch.object(input_bell, "_ring_bell", return_value=True):
            self.assertEqual(input_bell._run_once("topsailai", None), (True, True))

    def test_run_once_reports_detected_but_not_played_when_bell_fails(self):
        """A failed bell is not reported as successfully played."""
        with mock.patch.object(
            input_bell, "_has_input_sessions", return_value=True
        ), mock.patch.object(input_bell, "_ring_bell", return_value=False):
            self.assertEqual(input_bell._run_once("topsailai", None), (True, False))

    def _tmpdir(self):
        """Create an isolated temporary directory for one test fixture."""
        import tempfile

        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return directory.name

class TestInputBellTestSound(TestCase):
    """Verify the one-shot --test-sound parameter."""

    def setUp(self):
        """Clear the process-local probe cache between tests."""
        input_bell._AUTO_SOUND_COMMAND = None

    def tearDown(self):
        """Leave the module cache empty for unrelated tests."""
        input_bell._AUTO_SOUND_COMMAND = None

    def test_parse_args_accepts_test_sound_flag(self):
        """--test-sound parses into a True flag and defaults to False."""
        self.assertTrue(input_bell._parse_args(["--test-sound"]).test_sound)
        self.assertFalse(input_bell._parse_args([]).test_sound)

    def test_main_test_sound_returns_zero_when_bell_plays(self):
        """A successful one-shot sound test exits with code 0."""
        with mock.patch.object(input_bell, "_ring_bell", return_value=True) as ring:
            self.assertEqual(input_bell.main(["--test-sound"]), 0)

        ring.assert_called_once_with(None)

    def test_main_test_sound_returns_one_when_bell_fails(self):
        """A failed one-shot sound test exits with code 1."""
        with mock.patch.object(input_bell, "_ring_bell", return_value=False) as ring:
            self.assertEqual(input_bell.main(["--test-sound"]), 1)

        ring.assert_called_once_with(None)

    def test_main_test_sound_bypasses_input_session_check(self):
        """The sound test never queries `topsailai workspace`."""
        with mock.patch.object(input_bell, "_ring_bell", return_value=True), mock.patch.object(
            input_bell, "_has_input_sessions"
        ) as sessions:
            self.assertEqual(input_bell.main(["--test-sound"]), 0)

        sessions.assert_not_called()

    def test_main_test_sound_uses_configured_sound_command(self):
        """The configured sound command is honored during the sound test."""
        with mock.patch.dict(
            os.environ, {"TOPSAILAI_INPUT_BELL_SOUND": "ffplay -custom"}
        ), mock.patch.object(input_bell, "_ring_bell", return_value=True) as ring:
            self.assertEqual(input_bell.main(["--test-sound"]), 0)

        ring.assert_called_once_with("ffplay -custom")
