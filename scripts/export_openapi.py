"""Write the Web API's OpenAPI schema to ``web/openapi.json`` for the frontend types.

    .venv/bin/python scripts/export_openapi.py
    npm --prefix web run api:types

The frontend generates ``web/src/lib/api-schema.ts`` from this file, so a changed response model
breaks the frontend type check instead of the running page. ``tests/test_openapi_contract.py``
fails while the committed schema differs from the routes.

The schema comes from the routes alone: the app is built around an empty container, so no
database, settings, provider, or scheduler is touched.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

from calendar_sync.bootstrap.container import Container
from calendar_sync.interfaces.api.app import create_app

SCHEMA_PATH = Path(__file__).resolve().parents[1] / "web" / "openapi.json"


def openapi_document() -> str:
    # Only the lifespan reads the container, and building the schema never starts it.
    app = create_app(cast(Container, SimpleNamespace(scheduler=None)))
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main() -> None:
    SCHEMA_PATH.write_text(openapi_document(), encoding="utf-8")


if __name__ == "__main__":
    main()
