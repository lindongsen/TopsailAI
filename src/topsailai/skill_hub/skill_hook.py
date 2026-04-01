'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-01
  Purpose:
    This module provides hook functionality for skill execution.
    It allows registering and executing hooks before and after skill calls,
    and supports session locking and refreshing based on environment configuration.
'''

from topsailai.logger import logger
from topsailai.utils import (
    env_tool,
    module_tool,
)
from topsailai.ai_base.agent_types.exception import DataAgentRefreshSession
from topsailai.skill_hub.skill_tool import (
    is_matched_skill,
)


g_hooks = {}


class SkillHookData(object):
    """Data class for skill hook configuration and initialization.

    This class manages hook-related data for skills, including:
    - Skill folder identification
    - Command list for skill execution
    - Session locking configuration
    - Session refresh configuration
    - External hook modules registration

    Attributes:
        skill_folder (str): The folder path of the skill.
        cmd_list (list[str]): List of commands associated with the skill.
        need_lock_session (bool): Whether session locking is required for this skill.
        need_refresh_session (bool): Whether session refresh is required for this skill.
        data_agent_refresh_session (DataAgentRefreshSession): Session refresh data object.
        hooks (dict): Dictionary of registered hooks.
    """

    def __init__(
            self,
            skill_folder: str,
            cmd_list: list[str],
        ):
        """Initialize SkillHookData with skill folder and command list.

        Args:
            skill_folder (str): The folder path of the skill.
            cmd_list (list[str]): List of commands associated with the skill.
        """
        self.skill_folder = skill_folder
        self.cmd_list = cmd_list
        self.need_lock_session = None
        self.need_refresh_session = None

        self.data_agent_refresh_session = DataAgentRefreshSession(None, None)
        self.hooks = g_hooks

        self.init()

    def init(self):
        """Initialize hook data by reading environment configuration.

        This method performs the following initialization steps:
        1. Check if session locking is needed based on TOPSAILAI_SESSION_LOCK_ON_SKILLS env var
        2. Check if session refresh is needed based on TOPSAILAI_SESSION_REFRESH_ON_SKILLS env var
        3. Load external hook modules from TOPSAILAI_HOOK_MODULE_SKILLS env var

        The initialization determines whether the skill requires session locking
        or session refresh based on environment variable configuration and skill matching.
        """
        # lock session
        need_lock_session = False

        _skills_need_lock_session = env_tool.EnvReaderInstance.get_list_str(
            "TOPSAILAI_SESSION_LOCK_ON_SKILLS", separator=None,
        ) or []
        if is_matched_skill(self.skill_folder, _skills_need_lock_session):
            need_lock_session = True

        self.need_lock_session = need_lock_session

        # refresh session
        need_refresh_session = False
        _skills_need_refresh_session = env_tool.EnvReaderInstance.get_list_str(
            "TOPSAILAI_SESSION_REFRESH_ON_SKILLS", separator=None,
        ) or []
        if is_matched_skill(self.skill_folder, _skills_need_refresh_session):
            need_refresh_session = True

        self.need_refresh_session = need_refresh_session

        # hooks
        if not self.hooks:
            _skill_hooks = env_tool.EnvReaderInstance.get_list_str(
                "TOPSAILAI_HOOK_MODULE_SKILLS", separator=None,
            ) or []
            for _hook_module in _skill_hooks:
                _hooks = module_tool.get_external_function_map(_hook_module, key="HOOKS")
                if _hooks:
                    self.hooks.update(_hooks)

        return


class SkillHookHandler(SkillHookData):
    """Handler class for executing skill hooks.

    Extends SkillHookData to provide hook execution functionality.
    Supports before and after hooks for skill execution lifecycle.

    Class Constants:
        KEY_HANDLE_BEFORE_CALL_SKILL: Key for hooks executed before skill call.
        KEY_HANDLE_AFTER_CALL_SKILL: Key for hooks executed after skill call.
    """

    KEY_HANDLE_BEFORE_CALL_SKILL = "handle_before_call_skill"
    KEY_HANDLE_AFTER_CALL_SKILL = "handle_after_call_skill"

    def _call_hook(self, key: str):
        """Execute all hooks that match the given key suffix.

        Iterates through registered hooks and executes those whose names end with
        the specified key. Exceptions during hook execution are logged but do not
        interrupt other hook executions.

        Args:
            key (str): The suffix to match against hook names for execution.
        """
        if not self.hooks:
            return

        for hook_name, hook_func in self.hooks.items():
            if hook_name.endswith(key):
                try:
                    hook_func(self)
                except Exception as e:
                    logger.exception(
                        "call hook failed: [%s] [%s], %s",
                        hook_name, hook_func, e
                    )
        return

    def handle_before_call_skill(self):
        """Execute all hooks registered for pre-skill execution.

        This method triggers hooks that should run before a skill is called,
        allowing for pre-processing, validation, or setup operations.
        """
        self._call_hook(self.KEY_HANDLE_BEFORE_CALL_SKILL)
        return

    def handle_after_call_skill(self):
        """Execute all hooks registered for post-skill execution.

        This method triggers hooks that should run after a skill is called,
        allowing for post-processing, cleanup, or result handling operations.
        """
        self._call_hook(self.KEY_HANDLE_AFTER_CALL_SKILL)
        return
