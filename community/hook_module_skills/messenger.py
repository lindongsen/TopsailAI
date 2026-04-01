'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-01
  Purpose:
'''

from topsailai.skill_hub.skill_tool import (
    is_matched_skill,
)
from topsailai.skill_hub.skill_hook import (
    SkillHookHandler,
)

KEY_SKILL_FOLDER = "ai-community"

def handle_hook_before_call_skill(self:SkillHookHandler):
    """ Run before a skill is called """
    if not is_matched_skill(self.skill_folder, [KEY_SKILL_FOLDER]):
        return

    # get tool_request
    if self.need_refresh_session:
        message_head = ""
        message_body = ""
        for i, k in enumerate(self.cmd_list):
            if i == 0:
                continue
            if k.endswith("-receiver"):
                message_head = "To '%s':\n" % self.cmd_list[i+1]
                if message_body:
                    break
            elif k.endswith("-message"):
                message_body = self.cmd_list[i+1]
                if message_head:
                    break
        if message_body:
            self.data_agent_refresh_session.tool_request = message_head + message_body
        else:
            self.need_refresh_session = False

    return

def handle_hook_after_call_skill(self:SkillHookHandler):
    """ Run After a skill is called """
    if not is_matched_skill(self.skill_folder, [KEY_SKILL_FOLDER]):
        return

    # get tool_result
    if self.need_refresh_session:
        result = self.data_agent_refresh_session.tool_result
        if isinstance(result, (list, tuple)):

            # cmd result, code is 0
            if result[0] == 0:
                self.data_agent_refresh_session.tool_result = result[1]

    return

HOOKS = {
    SkillHookHandler.KEY_HANDLE_BEFORE_CALL_SKILL: handle_hook_before_call_skill,
    SkillHookHandler.KEY_HANDLE_AFTER_CALL_SKILL: handle_hook_after_call_skill,
}
