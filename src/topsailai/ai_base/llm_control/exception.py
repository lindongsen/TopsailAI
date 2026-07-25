'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-02-27
  Purpose:
'''

class JsonError(Exception):
    """ invalid json string """
    pass

class ModelServiceError(Exception):
    pass


class LLMServiceSpecialResponseError(ModelServiceError):
    """Raised when the LLM returns a configured special response that should be retried."""
    pass
