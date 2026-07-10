from rest_framework.response import Response
from rest_framework.views import exception_handler


class LlmConfigurationError(ValueError):
    pass


class LlmResponseError(RuntimeError):
    pass


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is not None:
        return response
    if isinstance(exc, LlmConfigurationError):
        return Response({'detail': str(exc), 'code': 'llm_not_configured'}, status=400)
    if isinstance(exc, LlmResponseError):
        return Response({'detail': str(exc), 'code': 'llm_failure'}, status=502)
    return None
