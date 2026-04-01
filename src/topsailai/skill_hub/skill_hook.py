'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-01
  Purpose:
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


class SkillHookData(object):
    def __init__(
            self,
            skill_folder:str,
            cmd_list:list[str],
        ):
        self.skill_folder = skill_folder
        self.cmd_list = cmd_list
        self.need_lock_session = None
        self.need_refresh_session = None

        self.data_agent_refresh_session = DataAgentRefreshSession(None, None)
        self.hooks = {}

        self.init()

    def init(self):
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
        _skill_hooks = env_tool.EnvReaderInstance.get_list_str(
            "TOPSAILAI_HOOK_MODULE_SKILLS", separator=None,
        )
        for _hook_module in _skill_hooks:
            _hooks = module_tool.get_external_function_map(_hook_module, key="HOOKS")
            if _hooks:
                self.hooks.update(_hooks)

        return

class SkillHookHandler(SkillHookData):

    KEY_HANDLE_BEFORE_CALL_SKILL = "handle_before_call_skill"
    KEY_HANDLE_AFTER_CALL_SKILL = "handle_after_call_skill"

    def _call_hook(self, key:str):
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
        self._call_hook(self.KEY_HANDLE_BEFORE_CALL_SKILL)
        return

    def handle_after_call_skill(self):
        self._call_hook(self.KEY_HANDLE_AFTER_CALL_SKILL)
        return
