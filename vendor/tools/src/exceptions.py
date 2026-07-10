from .utils import (
    InvalidJSONError,
)


__all__ = [
    "NoneError",
    "InvalidJSONError",
    "AttemptsExceededError",
]


class NoneError(Exception):
    def __init__(self, message: str = "NoneError") -> None:
        super().__init__(message)


class AttemptsExceededError(Exception):
    def __init__(self, message: str = "AttemptsExceededError") -> None:
        super().__init__(message)