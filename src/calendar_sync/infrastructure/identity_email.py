"""Verified SMTP delivery reserved for identity email."""

import ipaddress
import re
import smtplib
import ssl
from dataclasses import dataclass, field
from email.headerregistry import Address
from email.message import EmailMessage
from urllib.parse import urlsplit

from calendar_sync.application.identity.identity_email import IdentityEmailDeliveryFailed


def identity_loopback(host: str) -> bool:
    """Trust literal loopback only, never DNS resolution."""
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def identity_origin(value: str) -> str | None:
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        return None
    if any(char in value for char in ("?", "#", "\\", "%")):
        return None
    try:
        parts = urlsplit(value)
        host, port = parts.hostname, parts.port
    except ValueError:
        return None
    if (
        parts.scheme not in {"https", "http"}
        or not host
        or parts.username is not None
        or parts.password is not None
        or parts.path not in {"", "/"}
    ):
        return None
    if not _safe_authority(parts.netloc, host):
        return None
    if port is not None and not 1 <= port <= 65535:
        return None
    if parts.scheme == "http" and not identity_loopback(host):
        return None
    if ":" in host:
        host = f"[{host}]"
    suffix = (
        f":{port}" if port is not None and port != (443 if parts.scheme == "https" else 80) else ""
    )
    return f"{parts.scheme}://{host}{suffix}"


@dataclass(frozen=True, slots=True)
class IdentitySmtp:
    host: str
    port: int
    sender: str
    username: str = field(repr=False)
    password: str = field(repr=False)
    use_starttls: bool
    origin: str

    def send_test(self, recipient: str) -> None:
        try:
            self._send(recipient)
        except Exception:
            raise IdentityEmailDeliveryFailed() from None

    def _send(self, recipient: str) -> None:
        if not self.use_starttls and not identity_loopback(self.host):
            raise IdentityEmailDeliveryFailed()
        origin = identity_origin(self.origin)
        if origin is None:
            raise IdentityEmailDeliveryFailed()
        _single_mailbox(self.sender)
        _single_mailbox(recipient)
        message = EmailMessage()
        message["Subject"] = "Calendar Ghost: test email"
        message["From"] = self.sender
        message["To"] = recipient
        message.set_content(
            "Calendar Ghost can send identity email with the current settings.\n\n"
            f"Open Calendar Ghost: {origin}\n\n"
            "This test does not change who can join."
        )
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            if self.use_starttls:
                smtp.starttls(context=ssl.create_default_context())
            if self.username:
                smtp.login(self.username, self.password)
            smtp.send_message(message, from_addr=self.sender, to_addrs=[recipient])


def _safe_authority(authority: str, host: str) -> bool:
    if ":" in host:
        return re.fullmatch(r"\[[0-9a-fA-F:.]+\](?::[0-9]+)?", authority) is not None
    labels = host.rstrip(".").split(".")
    if any(
        re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label) is None
        for label in labels
    ):
        return False
    return re.fullmatch(r"[a-zA-Z0-9.-]+(?::[0-9]+)?", authority) is not None


def _single_mailbox(value: str) -> None:
    """Accept a bare mailbox only; headers must never expand the envelope."""
    if any(char.isspace() or ord(char) < 32 or ord(char) == 127 for char in value):
        raise IdentityEmailDeliveryFailed()
    address = Address(addr_spec=value)
    if not address.username or not address.domain or address.addr_spec != value:
        raise IdentityEmailDeliveryFailed()
