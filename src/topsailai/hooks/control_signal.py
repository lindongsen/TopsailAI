"""Explicit host control propagation across optional Module isolation."""


class HookControlSignal(BaseException):
    """Carry an intentionally raised host signal, not an ordinary plugin error."""

    def __init__(self, error):
        """Retain the original signal instance and its traceback."""
        from topsailai.ai_base.exception import HardInterruptError
        from topsailai.ai_base.llm_control.control_runtime import LLMRequestedRetryError
        if type(error) not in (HardInterruptError, LLMRequestedRetryError):
            raise TypeError("Unsupported Hook control signal")
        super().__init__()
        self.error = error
