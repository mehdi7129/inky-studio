"""Public display errors: stable codes and messages, never driver internals."""
from __future__ import annotations


class DisplayUnavailableError(RuntimeError):
    def __init__(self, detail: str, code: str = "display_unavailable") -> None:
        super().__init__(detail)
        self.detail = detail
        self.code = code

    def payload(self) -> dict[str, str]:
        return {"code": self.code, "detail": self.detail}


class DisplayConfirmationPending(DisplayUnavailableError):
    """The upstream sequence returned normally, without an observed refresh edge."""

    def __init__(self) -> None:
        super().__init__(
            "La fin de l’affichage n’a pas pu être confirmée. La photo est conservée. "
            "L’affichage automatique est suspendu ; vous pouvez réessayer manuellement.",
            "display_confirmation_pending",
        )
