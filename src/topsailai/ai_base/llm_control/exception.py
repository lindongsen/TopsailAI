'''
  Author: DawsonLin
  Email: lin_dongsen@126.com
  Created: 2026-02-27
  Purpose:
'''


class JsonError(Exception):
    """Report invalid JSON returned by a model."""


class ModelServiceError(Exception):
    """Report an invalid or unavailable model-service response."""


class LLMNullResponseError(ModelServiceError):
    """Report a model response whose content is null or blank."""


class LLMServiceSpecialResponseError(ModelServiceError):
    """Report a configured model response that should be retried."""


class LLMSevereRepetitionError(ModelServiceError):
    """Report a repetition verdict that survived the retry budget.

    This is a specialized model-service error: the response is unusable for the
    same reason a generic service error is, but retrying cannot fix it. The
    repetition verdict is computed from the response content, and a model that
    produced a repetitive answer once will usually produce it again, so the
    retry loop must stop instead of resending the identical request.

    It subclasses ``ModelServiceError`` so callers that already handle model
    service failures keep working. The retry loop must therefore catch this
    class *before* ``ModelServiceError`` and re-raise it, otherwise the generic
    branch would treat it as retryable and the fallback would never fire.
    """


class LLMRequestTimeoutError(ModelServiceError):
    """Report one logical LLM request that spent its wall-clock budget.

    This is a specialized model-service error: the request is unusable for the
    same reason a generic service error is, but the cause is the retry loop
    itself rather than one provider reply. Every individual attempt may look
    short while the loop keeps resending the same request, so only a budget
    measured from the start of the request can bound the stall.

    It subclasses ``ModelServiceError`` so callers that already handle model
    service failures keep working. The retry loop must therefore never let the
    generic ``ModelServiceError`` branch catch it, because that branch treats
    the error as retryable and would resend the very request the budget exists
    to stop.
    """


class LLMProviderError(Exception):
    """Base error translated from an LLM provider SDK or transport."""

    def __init__(self, message="", *, response=None, body=None):
        """Retain provider-neutral diagnostics needed by request handling."""
        super().__init__(message)
        self.response = response
        self.body = body


class LLMProviderRateLimitError(LLMProviderError):
    """Report provider request throttling."""


class LLMProviderInternalServerError(LLMProviderError):
    """Report an internal provider service failure."""


class LLMProviderTimeoutError(LLMProviderError):
    """Report a provider request or first-byte timeout."""


class LLMProviderConnectionError(LLMProviderError):
    """Report a provider connection failure."""


class LLMProviderPermissionDeniedError(LLMProviderError):
    """Report provider authorization denial."""


class LLMProviderBadRequestError(LLMProviderError):
    """Report a provider rejection of the request payload."""


class LLMProviderReadError(LLMProviderError):
    """Report a provider transport read or protocol failure."""


# Backward-compatible project-owned alias retained for existing imports.
APITimeoutError = LLMProviderTimeoutError
