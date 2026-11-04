"""Note helpers exposed as /notes.* slash instructions."""

# List form: the action name is the function name, so this module registers
# /notes.add and /notes.list_notes.

_NOTES: list[str] = []


def add(text: str = "") -> str:
    """Append one note and report the new total."""
    if not text:
        return "Usage: /notes.add <text>"
    _NOTES.append(text)
    return f"added: {text} (total={len(_NOTES)})"


def list_notes() -> str:
    """List every note added in this process."""
    if not _NOTES:
        return "no notes yet"
    return "\n".join(f"{i}. {n}" for i, n in enumerate(_NOTES, 1))


INSTRUCTIONS = [add, list_notes]
