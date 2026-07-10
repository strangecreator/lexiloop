import json
import typing as tp

# local imports
import tools


__all__ = [
    "HTTPStatusError",
    "InvalidJSONResponseError",
    "EmptyBodyError",
]


class HTTPStatusError(Exception):
    def __init__(self, status: int, body: tp.Optional[tp.Any]):
        self.status = status
        self.body = body

        if isinstance(body, dict):
            msg = f"HTTP Status: {status}, `body` is of type {type(body)}:\n{json.dumps(self.body, indent=2, ensure_ascii=False)}"
        elif isinstance(body, str) and body != '':
            msg = f"HTTP Status: {status}, `body` is of type {type(body)}:\n{body}"
        elif isinstance(body, str) and body == '':
            msg = f"HTTP Status: {status}, `body` is of type {type(body)}, empty."
        else:
            msg = f"HTTP Status: {status}, `body` is of type {type(body)}."

        super().__init__(msg)


class InvalidJSONResponseError(Exception):
    def __init__(self, status: tp.Optional[int], body_text: str, end: str = "... (truncated)", max_len: int = 3000) -> None:
        self.status = status
        self.body_text = body_text
        self.body_text_truncated = tools.truncate_word_aware(body_text, end=end, max_len=max_len, save_spaces=True)

        super().__init__(f"Invalid JSON (status={status}): {self.body_text_truncated}")


class EmptyBodyError(Exception):
    def __init__(self, status: tp.Optional[int]) -> None:
        self.status = status

        super().__init__(f"Empty response body (status={status}).")


class DelayedError(Exception):
    def __init__(self, message: tp.Optional[str], end: str = "... (truncated)", max_len: int = 3000, color: str | None = None) -> None:
        self.message = message
        self.message_truncated = tools.truncate_word_aware(message, end=end, max_len=max_len, save_spaces=True)

        self.error_body = f"Request has been delayed: {self.message_truncated}"

        if color is not None:
            self.error_body = tools.colorize(self.error_body, tools.hex_color_from_string(color))

        super().__init__(self.error_body)


class DelayedRequestFailedError(Exception):
    def __init__(
        self,
        message: str,
        payload: dict[str, tp.Any],
        *,
        color: str = "invalid",
    ) -> None:
        super().__init__(message)

        self.color = color
        self.payload = payload

        self.request_hash = payload.get("request_hash")
        self.producer_key = payload.get("producer_key")
        self.consumer_key = payload.get("consumer_key")
        self.processing_key = payload.get("processing_key")
        self.url = payload.get("url")

        self.original_error_type = payload.get("error_type")
        self.original_error = payload.get("error")

    def __str__(self) -> str:
        base = super().__str__()

        error_type = self.original_error_type if isinstance(self.original_error_type, str) else None
        error_text = self.original_error if isinstance(self.original_error, str) else None

        if error_type is None and error_text is None:
            return base

        # keep it short by default (full thing is in .original_error / .payload)
        first_line = None
        if isinstance(error_text, str) and error_text.strip():
            first_line = error_text.strip().splitlines()[0]

        details = error_type or "UnknownError"
        if first_line:
            details = f"{details}: {first_line}"

        return f"{base} [{details}]"