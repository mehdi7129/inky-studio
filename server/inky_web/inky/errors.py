"""Public display errors: stable codes and messages, never driver internals."""
from __future__ import annotations


class DisplayUnavailableError(RuntimeError):
    def __init__(self, detail: str, code: str = "display_unavailable") -> None:
        super().__init__(detail)
        self.detail = detail
        self.code = code

    def payload(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}
