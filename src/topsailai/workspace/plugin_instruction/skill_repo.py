'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-03-26
  Purpose:
'''

from topsailai.skill_hub.skill_repo import (
    list_skills,
    install_skill,
    uninstall_skill,
)

INSTRUCTIONS = {
    "list": list_skills,
    "install": install_skill,
    "uninstall": uninstall_skill,
}
