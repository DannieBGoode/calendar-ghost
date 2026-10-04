from scripts.export_openapi import SCHEMA_PATH, openapi_document


def test_the_committed_openapi_schema_matches_the_routes() -> None:
    # The frontend's API types are generated from this file; a stale copy hides a broken contract.
    assert SCHEMA_PATH.read_text(encoding="utf-8") == openapi_document(), (
        "Run `.venv/bin/python scripts/export_openapi.py` and `npm --prefix web run api:types`."
    )
