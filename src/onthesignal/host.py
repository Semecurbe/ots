"""User host: how the assistant and the commands talk to the user (web specification R14).

The assistant does not know whether it runs in the console or in the web chat. It receives a
*host* that shows messages, asks for confirmations and runs code. The console
(:class:`onthesignal.cli.console.OnTheSignalConsole`) and the web interface each provide one.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class UserHost(Protocol):
    """What a user interface provides to the assistant."""

    #: Session the host works on.
    session: Any

    def info(self, text: str) -> None:
        """Show an information message."""

    def warning(self, text: str) -> None:
        """Show a warning."""

    def error(self, text: str) -> None:
        """Show an error."""

    def markdown(self, text: str) -> None:
        """Show an answer of the assistant (Markdown)."""

    def confirm(self, question: str, details: str = "", key: str | None = None) -> bool:
        """Ask the user to allow an action; ``details`` (code, arguments) is shown first.

        ``key`` names the kind of action (the tool of the assistant): a host may remember
        "allow for this chat" for it.
        """

    def run_python(self, code: str) -> None:
        """Run Python code in the session namespace."""


__all__ = ["UserHost"]
