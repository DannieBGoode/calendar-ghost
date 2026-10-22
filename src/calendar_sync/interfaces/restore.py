"""Safe terminal boundary for stopped-service database restoration."""

import argparse
import getpass
import warnings
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Never

from calendar_sync.application.identity.errors import PasswordPolicyViolation
from calendar_sync.application.identity.sign_in import require_password
from calendar_sync.application.operations.restoration import OfflineRestore, RestoreFailure


class RestoreParser(argparse.ArgumentParser):
    def error(self, _message: str) -> Never:
        self.print_help()
        raise RestoreFailure("usage_invalid")


def _parser() -> RestoreParser:
    parser = RestoreParser(
        prog="calendar-ghost-restore",
        description="Offline restoration. Cannot verify that processes are stopped.",
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("inspect", "prepare"):
        sub = commands.add_parser(command, allow_abbrev=False)
        sub.add_argument("--database", type=Path, required=True)
        if command == "prepare":
            sub.add_argument("--backup", type=Path, required=True)
            sub.add_argument("--administrator-id", required=True)
            sub.add_argument("--acknowledge-services-stopped", action="store_true")
    return parser


def _password() -> str:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", getpass.GetPassWarning)
            password = getpass.getpass("New administrator password: ")
            confirmation = getpass.getpass("Confirm administrator password: ")
        require_password(password)
        if len(password) > 256 or password != confirmation:
            raise RestoreFailure("password_invalid")
        return password
    except PasswordPolicyViolation:
        raise RestoreFailure("password_invalid") from None
    except (EOFError, KeyboardInterrupt, OSError, UnicodeError, getpass.GetPassWarning):
        raise RestoreFailure("password_input_failed") from None


def run(argv: Sequence[str] | None, factory: Callable[[Path], OfflineRestore]) -> int:
    try:
        args = _parser().parse_args(argv)
        if args.command == "prepare" and not args.acknowledge_services_stopped:
            raise RestoreFailure("services_not_acknowledged")
        service = factory(args.database)
        if args.command == "inspect":
            result = service.inspect()
            key = "key_authenticated" if result.authenticated_credentials else "key_unverified"
            print(
                f"inspected schema_version={result.schema_version} users={result.users} "
                f"accounts={result.accounts} authenticated_credentials="
                f"{result.authenticated_credentials} {key}"
            )
        else:
            prepared = service.prepare(args.backup, args.administrator_id, _password(), True)
            print(
                f"prepared disabled_users={prepared.disabled_users} "
                f"disconnected_accounts={prepared.disconnected_accounts}"
            )
            for category, count in prepared.invalidated_records:
                print(f"{category}={count}")
        return 0
    except RestoreFailure as error:
        import sys

        print(error.code, file=sys.stderr)
        return error.status
    except SystemExit as error:
        return int(error.code or 0)
