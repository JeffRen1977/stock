from __future__ import annotations

from dataclasses import dataclass
import shutil
import subprocess


@dataclass(frozen=True)
class SendResult:
    recipient: str
    success: bool
    message_sid: str | None = None
    error: str | None = None


class OpenClawWhatsAppSender:
    def __init__(self, openclaw_bin: str = "openclaw") -> None:
        self.openclaw_bin = openclaw_bin

    def send_to_many(self, recipients: tuple[str, ...], body: str) -> list[SendResult]:
        return [self.send(recipient, body) for recipient in recipients]

    def send(self, recipient: str, body: str) -> SendResult:
        if shutil.which(self.openclaw_bin) is None:
            return SendResult(
                recipient=recipient,
                success=False,
                error=f"{self.openclaw_bin} command was not found in PATH",
            )

        target = _normalize_openclaw_target(recipient)
        command = [
            self.openclaw_bin,
            "message",
            "send",
            "--channel",
            "whatsapp",
            "--target",
            target,
            "--message",
            body,
            "--json",
        ]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if completed.returncode == 0:
            return SendResult(
                recipient=recipient,
                success=True,
                message_sid=completed.stdout.strip() or "openclaw",
            )

        return SendResult(
            recipient=recipient,
            success=False,
            error=(completed.stderr or completed.stdout).strip(),
        )


def build_whatsapp_sender() -> OpenClawWhatsAppSender:
    return OpenClawWhatsAppSender()


def _normalize_openclaw_target(recipient: str) -> str:
    target = recipient.strip()
    if target.startswith("whatsapp:"):
        target = target.removeprefix("whatsapp:")
    return target
