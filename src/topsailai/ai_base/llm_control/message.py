'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-02-27
  Purpose:
'''

import simplejson
from openai.types.chat import (
    ChatCompletionMessage,
)

from topsailai.logger.log_chat import logger
from topsailai.utils.print_tool import (
    print_error,
)
from topsailai.utils import (
    format_tool,
    json_tool,
)
from topsailai.ai_base.llm_hooks.executor import hook_execute

from .exception import (
    JsonError,
    ModelServiceError,
)


def _to_list(obj):
    """
    Convert an object to a list if it is not already a list.

    Args:
        obj: The object to convert. Can be any type.

    Returns:
        list or None: Returns the object as a list if it's a list-like type,
        returns None if obj is None, otherwise returns a single-item list containing obj.

    Examples:
        >>> _to_list([1, 2, 3])
        [1, 2, 3]
        >>> _to_list("hello")
        ["hello"]
        >>> _to_list(None)
        None
        >>> _to_list((1, 2, 3))
        [1, 2, 3]
    """
    if isinstance(obj, list):
        return obj
    if obj is None:
        return None
    if isinstance(obj, (set, tuple)):
        return list(obj)
    return [obj]

def get_response_message(response) -> ChatCompletionMessage:
    """
    Extract the message from the API response.

    Args:
        response: The API response object

    Returns:
        ChatCompletionMessage: The assistant's message from the response

    Example:
        ChatCompletionMessage(
            content='',
            refusal=None,
            role='assistant',
            annotations=None,
            audio=None,
            function_call=None,
            tool_calls=None),
            refs=None,
            service_tier=None
        )
    """
    if isinstance(response, ChatCompletionMessage):
        return response
    return response.choices[0].message

def format_messages(messages, key_name, value_name):
    """
    Format messages to a specific format for the assistant.

    This function processes messages to apply TopsailAI-specific formatting
    when the first message contains the TopsailAI format prefix.

    Args:
        messages (list): List of message dictionaries with 'content' keys
        key_name (str): The key name to use for formatting
        value_name (str): The value name to use for formatting

    Returns:
        list: The formatted messages list

    Note:
        Only processes messages starting from index 2 (skipping system and user messages)
        that contain JSON-like content (starting with '[' or '{')
    """

    new_messages = hook_execute("TOPSAILAI_HOOK_BEFORE_LLM_CHAT", messages)
    if new_messages:
        messages = new_messages

    func_format = None  # func(content, key_name, value_name)

    if format_tool.TOPSAILAI_FORMAT_PREFIX in messages[0]["content"]:
        func_format = format_tool.to_topsailai_format

    if func_format is None:
        return messages

    for msg in messages[2:]:
        if msg["content"][0] in ["[", "{"]:
            new_content = func_format(
                msg["content"],
                key_name=key_name,
                value_name=value_name,
            )
            if new_content:
                msg["content"] = new_content.strip()

    #logger.info(simplejson.dumps(messages, indent=2, default=str))

    return messages

def fix_llm_mistakes(response:list, rsp_obj=None):
    if not response:
        return response

    # case: only tool_call and tool_args, missing step_name
    if len(response) == 1:
        item = response[0]
        if len(item) == 2:
            if 'tool_call' in item and 'tool_args' in item:
                print_error("fix llm mistake: missing step_name")
                item["step_name"] = "action"
        elif len(item) == 1:
            if 'tool_call' in item:
                print_error("fix llm mistake: missing step_name")
                item["step_name"] = "action"

    # case: tool_calls in rsp_obj
    if response and isinstance(response, list) and rsp_obj is not None:
        if len(response) == 1:
            item0 = response[0]
            rsp_msg = get_response_message(rsp_obj)

            if rsp_msg is None:
                return response

            if not isinstance(item0, dict):
                return response

            # case: missing action
            if "step_name" in item0 \
                and item0["step_name"] != "action" \
                and rsp_msg.tool_calls:
                    print_error("fix llm mistake: missing step_name=action")
                    response.append(
                        {"step_name": "action"}
                    )

    return response

def assert_model_service_error(response):
    """ raise ModelServiceError if error """
    if not response:
        return
    if len(response) != 1:
        return

    item0 = response[0]
    if isinstance(item0, dict):
        if 'step_name' not in item0:

            # case: only status and message
            if len(item0) == 2 and 'message' in item0 and 'status' in item0:
                raise ModelServiceError(f"some errors have occurred in model service: [{item0}]")

            # case
            #  {
            #       "status": 20223,
            #       "message": "Input token exceeded",
            #       "result": null,
            #       "timestamp": 1769046649634
            #  }
            if 'message' in item0 and 'status' in item0:
                raise ModelServiceError(f"some errors have occurred in model service: [{item0}]")
                # for key in [
                #     'exceed',
                # ]:
                #     if key in item0["message"]:
                #         raise ModelServiceError(f"some errors have occurred in model service: [{item0}]")

    return

def get_count_of_action(messages:list) -> int:
    if not messages:
        return 0
    count = 0
    for msg in messages[2:]:
        if not isinstance(msg, dict):
            continue
        if 'content' not in msg:
            continue

        if '"step_name": "action"' in msg["content"]:
            count += 1
    return count

def format_response(response, rsp_obj=None, messages=None):
    """
    Format response to a standardized list format for internal use.

    This function handles various response formats and converts them to a
    consistent list-of-dictionaries format. It supports:
    - Already formatted lists/dictionaries
    - JSON strings
    - TopsailAI format strings

    Args:
        response: The response to format. Can be list, dict, or string.

    Returns:
        list: A list of dictionaries in standardized format

    Raises:
        JsonError: If the response cannot be parsed after multiple attempts

    Note:
        Attempts parsing up to 3 times, handling TopsailAI format first,
        then falling back to standard JSON parsing.
    """
    if isinstance(response, (list, dict)):
        return _to_list(response)

    if isinstance(response, str):
        response = response.strip()
        if not response:
            raise JsonError("null of response")

    for count in range(3):
        try:
            if response.startswith(format_tool.TOPSAILAI_FORMAT_PREFIX) \
                or f"\n{format_tool.TOPSAILAI_FORMAT_PREFIX}" in response \
                or f"{format_tool.TOPSAILAI_STEP_ACTION}\n" in response \
                or f"{format_tool.TOPSAILAI_STEP_THINK}\n" in response \
                :
                    if count:
                        # no need retry
                        break
                    response = format_tool.format_dict_to_list(
                        format_tool.parse_topsailai_format(response),
                        key_name="step_name",
                        value_name="raw_text",
                    )
                    return response

            response = json_tool.to_json_str(response)
            response = _to_list(simplejson.loads(response))
            fix_llm_mistakes(response)

            # model service have errors. example: Model tpm limit exceeded
            assert_model_service_error(response)

            return response
        except ModelServiceError as e:
            raise e
        except Exception as e:
            print_error(f"parsing response: {e}\n>>>\n{response}\n<<<\nretrying times: {count}")
        finally:
            fix_llm_mistakes(response, rsp_obj)

            # hook after chat
            if isinstance(response, list):
                if len(response) == 1:
                    item = response[0]
                    if len(item) == 2 and item.get("step_name") == "action" and item.get("raw_text"):
                        item_extra = hook_execute("TOPSAILAI_HOOK_AFTER_LLM_CHAT", item["raw_text"])
                        if item_extra and isinstance(item_extra, list) and len(item_extra) == 1:
                            print_error("fix llm mistake: TOPSAILAI_HOOK_AFTER_LLM_CHAT, action content format is unexpected")
                            item.update(item_extra[0])

                    # case: only thought
                    if item.get("step_name") == "thought":
                        action_count = get_count_of_action(messages)
                        if action_count > 0:
                            print_error(f"fix llm mistake: maybe final answer due to found action count [{action_count}]")
                            item["step_name"] = "final_answer"

    # hook after chat
    new_response = hook_execute("TOPSAILAI_HOOK_AFTER_LLM_CHAT", response)
    if new_response and new_response != response:
        print_error("fix llm mistake: TOPSAILAI_HOOK_AFTER_LLM_CHAT")
        response = new_response
        if not isinstance(response, str):
            return response

    # only thought
    if response and format_tool.TOPSAILAI_FORMAT_PREFIX not in response \
        and response[0] not in "[]{}" \
        and (response[-1] not in "[]{}" or response[:5] not in "[{"):
            print_error("fix llm mistake: maybe only thought")
            step_name = format_tool.TOPSAILAI_STEP_THINK

            action_count = get_count_of_action(messages)
            if action_count > 0:
                print_error(f"fix llm mistake: maybe final answer due to found action count [{action_count}]")
                step_name = format_tool.TOPSAILAI_STEP_FINAL

            return format_response(step_name + "\n" + response, rsp_obj=rsp_obj)

    raise JsonError("invalid json string")
