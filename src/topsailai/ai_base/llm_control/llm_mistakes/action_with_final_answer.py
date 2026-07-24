'''
Author: DawsonLin
Email: lin_dongsen@126.com
Created: 2026-07-24
Purpose: Fix responses that contain both action and final answer steps.
'''


def _is_final_step(item):
    """Return whether an item represents a final response step."""
    return (
        isinstance(item, dict)
        and str(item.get("step_name", "")).startswith("final")
    )


def fix_action_with_final_answer(message, **_):
    """Convert premature final steps to thought content when an action exists."""
    if not isinstance(message, list):
        return None

    has_action = any(
        isinstance(item, dict) and item.get("step_name") == "action"
        for item in message
    )
    final_items = [item for item in message if _is_final_step(item)]
    if not has_action or not final_items:
        return None

    first_thought_index = next((
        index
        for index, item in enumerate(message)
        if isinstance(item, dict) and item.get("step_name") == "thought"
    ), None)

    if first_thought_index is None:
        return [
            {
                **item,
                "step_name": "thought",
            } if _is_final_step(item) else item
            for item in message
        ]

    fixed_message = []
    fixed_thought_index = None
    for index, item in enumerate(message):
        if _is_final_step(item):
            continue
        if index == first_thought_index:
            fixed_thought_index = len(fixed_message)
            item = dict(item)
        fixed_message.append(item)

    thought = fixed_message[fixed_thought_index]
    thought_text = str(thought.get("raw_text") or "")
    final_texts = [str(item.get("raw_text") or "") for item in final_items]
    thought["raw_text"] = "\n".join([thought_text, *final_texts])
    return fixed_message


MISTAKES = dict(
    fix_action_with_final_answer=fix_action_with_final_answer,
)
