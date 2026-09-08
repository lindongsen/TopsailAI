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


class LLMServiceSpecialResponseError(ModelServiceError):
    """Report a configured model response that should be retried."""


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
