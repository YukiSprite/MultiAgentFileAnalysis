"""Errors surfaced by the web console."""


class ConsoleError(Exception):
    """An error that maps directly onto an HTTP response."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
