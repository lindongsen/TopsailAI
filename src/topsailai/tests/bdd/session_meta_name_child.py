"""Author: DawsonLin. Real Agent and HTTP naming metadata observations."""

import json
import os
import threading
from pathlib import Path

from topsailai.context import ctx_manager
from topsailai.workspace import agent_shell, llm_shell, session_meta


def main():
    """Run a new session and resume its stored name without a new request."""
    workers = []
    naming_chats = []
    original_threading = ctx_manager.threading
    original_get_chat = llm_shell.get_llm_chat
    original_thread = original_threading.Thread

    class NamingThread(original_thread):
        """Record only the exact auto-name worker before it starts."""
        def start(self):
            """Retain naming workers without intercepting unrelated threads."""
            if self._target is ctx_manager._async_update_session_name:
                workers.append(self)
            return super().start()

    class ThreadingProxy:
        """Delegate threading operations while replacing only Thread locally."""
        Thread = NamingThread

        def __getattr__(self, name):
            """Resolve non-Thread attributes from the real threading module."""
            return getattr(original_threading, name)

    def track_chat(*args, **kwargs):
        """Retain the real naming client's cleanup owner."""
        chat = original_get_chat(*args, **kwargs)
        naming_chats.append(chat)
        return chat

    ctx_manager.threading = ThreadingProxy()
    llm_shell.get_llm_chat = track_chat
    session_id = os.environ["BDD_SESSION_ID"]
    chats = []
    snapshots = {"expected_hostname": session_meta.socket.gethostname()}

    def make_chat():
        """Construct the public shell without external workspace locking."""
        chat = agent_shell.get_agent_chat(
            agent_type="react", agent_role="manager", session_id=session_id,
            message="Name this metadata regression task", need_input_message=False,
            need_print_session=False, need_set_agent_name_to_thread_local=False,
            need_project_workspace_lock=False,
        )
        chats.append(chat)
        return chat

    def read_meta():
        """Inspect the actual current-PID metadata publication."""
        return json.loads(Path(session_meta.get_session_meta_path(session_id)).read_text())

    def join_workers(_agent=None):
        """Observe naming completion before allowing session completion."""
        failures = []
        for worker in workers:
            worker.join(10)
            if worker.is_alive():
                failures.append("naming worker did not exit")
        if failures:
            raise AssertionError("; ".join(failures))
        snapshots["named"] = read_meta()
        snapshots["db_name"] = ctx_manager.get_session_manager().get_session(session_id).session_name

    cleanup_error = None
    try:
        chat = make_chat()
        snapshots["created"] = read_meta()
        chat.hooks_post_succ_run.append(join_workers)
        chat.run(message=chat.first_message, times=1, need_interactive=False)
        snapshots["completed"] = read_meta()
        make_chat()
        snapshots["resumed"] = read_meta()
        Path(os.environ["BDD_INTEGRITY_REPORT"]).write_text(json.dumps(snapshots))
    finally:
        try:
            for worker in workers:
                worker.join(10)
                if worker.is_alive() and cleanup_error is None:
                    cleanup_error = AssertionError("naming worker did not exit")
        finally:
            try:
                for chat in chats + naming_chats:
                    chat.close() if chat in naming_chats else chat.ai_agent.close()
            finally:
                ctx_manager.threading = original_threading
                llm_shell.get_llm_chat = original_get_chat
        if cleanup_error is not None:
            raise cleanup_error


if __name__ == "__main__":
    main()
