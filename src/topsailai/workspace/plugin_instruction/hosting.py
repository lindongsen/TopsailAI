"""Session-owned background script supervision. Author: DawsonLin."""

import atexit
from dataclasses import dataclass, field
import logging
import threading

from topsailai.scripts import start_script

logger = logging.getLogger(__name__)


@dataclass
class _Launch:
    """Keep exact ownership and publication facts for one launch."""

    session_id: str
    ready: threading.Event = field(default_factory=threading.Event)
    done: threading.Event = field(default_factory=threading.Event)
    stop: threading.Event = field(default_factory=threading.Event)
    thread: threading.Thread | None = None
    process: object = None
    error: BaseException | None = None
    cleanup_failed: bool = False


class HostingController:
    """Hold the launcher context until the child exits or the process shuts down."""

    def __init__(self, *, launcher=None, startup_timeout=10.0):
        """Accept an explicit launcher seam without changing production authority."""
        self._startup_timeout = startup_timeout
        self._launcher = launcher or start_script
        self._lock = threading.Lock()
        self._launch = None
        self._closed = False
        self._exit_registered = False

    def start(self, session_id):
        """Publish a spawned child once; reject missing IDs before any resources."""
        if not isinstance(session_id, str) or not session_id.strip():
            raise ValueError("Cannot start hosting: session_id is required")
        session_id = session_id.strip()
        startup_error = None
        with self._lock:
            if self._closed:
                raise RuntimeError("Hosting controller is closed")
            launch = self._launch
            duplicate = launch is not None and not launch.done.is_set()
            if launch is not None and launch.cleanup_failed:
                raise RuntimeError("Hosting cleanup remains unresolved") from launch.error
            if not duplicate:
                launch = _Launch(session_id)
                self._launch = launch
                if not self._exit_registered:
                    atexit.register(self._close_at_exit)
                    self._exit_registered = True
                try:
                    launch.thread = threading.Thread(
                        target=self._supervise, args=(launch,),
                        name="hosting-supervisor", daemon=True)
                except BaseException:
                    # Construction never called start, so no native worker exists.
                    launch.stop.set()
                    launch.ready.set()
                    self._release_exit_callback(launch)
                    launch.done.set()
                    raise
                try:
                    launch.thread.start()
                except BaseException as error:
                    startup_error = error
                    # An unpublished ident does not prove native creation failed.
                    launch.stop.set()
        if startup_error is not None:
            try:
                self._join(launch)
            except BaseException as cleanup_error:
                if isinstance(cleanup_error, (KeyboardInterrupt, SystemExit)):
                    raise cleanup_error from startup_error
                startup_error.add_note(f"Hosting cleanup failed: {cleanup_error!r}")
            raise startup_error
        try:
            if not launch.ready.wait(self._startup_timeout):
                raise TimeoutError("Hosting process creation timed out")
        except BaseException as primary:
            launch.stop.set()
            try:
                self._join(launch)
            except BaseException as cleanup_error:
                if isinstance(cleanup_error, (KeyboardInterrupt, SystemExit)):
                    raise cleanup_error from primary
                primary.add_note(f"Hosting cleanup failed: {cleanup_error!r}")
            raise
        if launch.error is not None:
            self._join(launch)
            raise launch.error
        if launch.process is None:
            raise RuntimeError("Hosting startup was cancelled")
        prefix = "Hosting already running" if duplicate else "Hosting process started"
        return f"{prefix}: session_id={launch.session_id} pid={launch.process.pid}"

    def _supervise(self, launch):
        """Own the context in one thread and always publish completion facts."""
        try:
            if launch.stop.is_set():
                return
            with self._launcher("session_agent_driver/session_agent_driver",
                                ["--session", launch.session_id]) as process:
                launch.process = process
                launch.ready.set()
                while process.poll() is None and not launch.stop.wait(0.05):
                    pass
                if process.returncode not in (None, 0):
                    logger.error("Hosting child exited session_id=%s pid=%s code=%s",
                                 launch.session_id, process.pid, process.returncode)
        except BaseException as error:
            launch.error = error
            launch.cleanup_failed = launch.process is not None
            logger.exception("Hosting supervision failed session_id=%s pid=%s",
                             launch.session_id, getattr(launch.process, "pid", None))
        finally:
            launch.ready.set()
            with self._lock:
                self._release_exit_callback(launch)
                launch.done.set()

    def _release_exit_callback(self, launch):
        """Retire exact settled ownership while the controller lock is held."""
        if self._launch is launch and not launch.cleanup_failed and self._exit_registered:
            atexit.unregister(self._close_at_exit)
            self._exit_registered = False

    def _join(self, launch):
        """Wait for completion even if the caller is interrupted during joining."""
        if launch.thread is None and launch.done.is_set():
            return
        interruption = None
        # Keep the slot and fallback armed if startup has no completion evidence.
        if launch.thread.ident is None and not launch.done.wait(self._startup_timeout):
            logger.error("Hosting thread startup remains unresolved session_id=%s stop=%s",
                         launch.session_id, launch.stop.is_set())
            raise RuntimeError("Hosting thread startup remains unresolved")
        while not launch.done.is_set() or launch.thread.is_alive():
            try:
                launch.thread.join(0.05)
            except BaseException as error:
                launch.stop.set()
                interruption = interruption or error
        if interruption is not None:
            raise interruption

    def close(self):
        """Stop supervision and retain unresolved cleanup evidence for the owner."""
        with self._lock:
            self._closed = True
            launch = self._launch
            if launch is not None:
                launch.stop.set()
        if launch is not None:
            self._join(launch)
            if launch.cleanup_failed:
                raise launch.error
        with self._lock:
            if launch is not None:
                self._release_exit_callback(launch)

    def _close_at_exit(self):
        """Provide best-effort hosting cleanup when the agent process exits."""
        try:
            self.close()
        except BaseException:
            logger.exception("Hosting shutdown fallback failed")


def hosting(*, session_id=None, controller):
    """Start supervised hosting for the current session, without command overrides."""
    return controller.start(session_id)


def bind_hosting(session_getter):
    """Keep supervision ownership local to the command callback."""
    controller = HostingController()

    def command():
        """Resolve the current session at invocation, not registration."""
        return hosting(session_id=session_getter(), controller=controller)

    return command
