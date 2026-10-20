"""A synthetic single-connection SMTP peer with ephemeral TLS certificates."""

import socket
import ssl
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Thread

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def certificate_context(directory: Path, hostname: str) -> tuple[ssl.SSLContext, Path]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Synthetic SMTP CA")])
    now = datetime.now(UTC)
    ca = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    leaf_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    leaf = (
        x509.CertificateBuilder()
        .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, hostname)]))
        .issuer_name(name)
        .public_key(leaf_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(hostname)]), critical=False)
        .sign(key, hashes.SHA256())
    )
    ca_path, cert_path, key_path = (
        directory / "ca.pem",
        directory / "server.pem",
        directory / "key.pem",
    )
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(leaf.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        leaf_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)
    return context, ca_path


@contextmanager
def smtp_server(
    context: ssl.SSLContext | None, *, refuse: bool = False
) -> Iterator[tuple[int, list[bytes]]]:
    messages: list[bytes] = []
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(3)
        thread = Thread(target=_serve, args=(listener, context, refuse, messages), daemon=True)
        thread.start()
        try:
            yield listener.getsockname()[1], messages
        finally:
            thread.join(timeout=4)
            assert not thread.is_alive()


def _serve(
    listener: socket.socket, context: ssl.SSLContext | None, refuse: bool, messages: list[bytes]
) -> None:
    try:
        connection, _ = listener.accept()
        connection.settimeout(3)
        _conversation(connection, context, refuse, messages)
    except (OSError, ssl.SSLError):
        pass


def _conversation(
    connection: socket.socket, context: ssl.SSLContext | None, refuse: bool, messages: list[bytes]
) -> None:
    with connection:
        stream = connection.makefile("rb")
        connection.sendall(b"220 synthetic SMTP\r\n")
        while line := stream.readline():
            command = line.split(b" ", 1)[0].strip().upper()
            if command == b"EHLO":
                connection.sendall(b"250-synthetic\r\n250 STARTTLS\r\n")
            elif command == b"STARTTLS":
                if refuse:
                    connection.sendall(b"454 TLS unavailable\r\n")
                    continue
                connection.sendall(b"220 Begin TLS\r\n")
                stream.close()
                assert context is not None
                connection = context.wrap_socket(connection, server_side=True)
                stream = connection.makefile("rb")
            elif command == b"DATA":
                connection.sendall(b"354 Send message\r\n")
                body = []
                while (part := stream.readline()) not in (b".\r\n", b""):
                    body.append(part)
                messages.append(b"".join(body))
                connection.sendall(b"250 Accepted\r\n")
            elif command == b"QUIT":
                connection.sendall(b"221 Bye\r\n")
                stream.close()
                connection.close()
                return
            else:
                connection.sendall(b"250 OK\r\n")
        stream.close()
        connection.close()
