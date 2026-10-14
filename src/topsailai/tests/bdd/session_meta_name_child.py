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
    original_thread = threading.Thread
    original_get_chat = llm_shell.get_llm_chat

    class NamingThread(original_thread):
        """Record the exact auto-name worker for deterministic observation."""
        def start(self):
            """Retain worker identity before starting its work."""
            workers.append(self)
            return super().start()

    def track_chat(*args, **kwargs):
        """Retain the real naming client's cleanup owner."""
        chat = original_get_chat(*args, **kwargs)
        naming_chats.append(chat)
        return chat

    ctx_manager.threading.Thread = NamingThread
    llm_shell.get_llm_chat = track_chat
    session_id = os.environ["BDD_SESSION_ID"]
    chats = []
    snapshots = {}

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
        for worker in workers:
            worker.join(10)
            assert not worker.is_alive(), "naming worker did not exit"
        snapshots["named"] = read_meta()
        snapshots["db_name"] = ctx_manager.get_session_manager().get_session(session_id).session_name

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
        for worker in workers:
            worker.join(10)
            assert not worker.is_alive()
        for chat in chats + naming_chats:
            chat.close() if chat in naming_chats else chat.ai_agent.close()
        ctx_manager.threading.Thread = original_thread
        llm_shell.get_llm_chat = original_get_chat


if __name__ == "__main__":
    main()
