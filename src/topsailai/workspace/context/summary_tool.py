'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-04-02
  Purpose:
'''

from topsailai.utils import (
    env_tool,
    format_tool,
)
from topsailai.prompt_hub import prompt_tool

g_summary_prompt_map = {}

def get_summary_prompt_extra_map() -> dict|None:
    """
    1. Get content from environ by this key "TOPSAILAI_SUMMARY_PROMPT_EXTRA_MAP",
        format is "key1=value1,value2;key2=value2"
    2. Parse content to dict, {key1: [value1, value2]}

    Returns:
        dict
    """
    if g_summary_prompt_map:
        return g_summary_prompt_map

    content = env_tool.EnvReaderInstance.get("TOPSAILAI_SUMMARY_PROMPT_EXTRA_MAP")
    if not content:
        return None

    result = format_tool.parse_str_to_dict(content, kv_strip=True)
    for k, v in result.items():
        v_set = v.split(',')
        result[k] = v_set

    g_summary_prompt_map.update(result)
    return result

def get_summary_prompt(agent_type:str) -> str:
    """ Get summary prompt content """
    summary_prompt_map = get_summary_prompt_extra_map()
    if not summary_prompt_map or agent_type not in summary_prompt_map:
        return ""

    result = ""
    for _file in summary_prompt_map[agent_type]:
        result += prompt_tool.read_prompt(_file)

    return result
