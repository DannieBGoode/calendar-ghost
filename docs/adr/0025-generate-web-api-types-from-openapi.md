# Generate the Web UI's API types from the OpenAPI schema

## Context

The Web UI described every API body by hand in `web/src/lib/api.ts`. Nothing checked those types
against the FastAPI response models, so a backend change could break a page with no failing check.
When the types were first compared, the hand-written ones had already missed two fields the API
sent: a Connected Account's `provider` and a discovered calendar's `access_role`. Three routes
(sync, reconcile, and preview) returned untyped dictionaries, so the schema did not describe them
at all.

The backend stays in Python (ADR 0001, ADR 0008), so the two halves cannot share one type
definition directly.

## Decision

- Every API route declares a Pydantic response model. Response models inherit `ApiResponse`, which
  marks fields with defaults as required in the schema, because the API always sends them.
  Fields whose values are a closed set use `Literal` types, so the schema lists the values.
- `scripts/export_openapi.py` writes the schema to `web/openapi.json` from the routes alone, without
  settings, a database, or a provider.
- `openapi-typescript` generates `web/src/lib/api-schema.ts` from that file. `web/src/lib/api.ts`
  names the generated types and adds no hand-written body types.
- Each `api` method calls its route through `call(path, method, inputs)`. The path template and
  method select every type from the generated `paths`: the path values, query, and body the route
  requires, and the body it returns. A call cannot leave out a required input, send one the route
  does not declare, or expect another route's body.
- Both files are committed. `tests/test_openapi_contract.py` fails when `web/openapi.json` differs
  from the routes, and `npm run api:check` fails when `api-schema.ts` differs from the schema. A
  changed response model therefore fails the frontend type check until the UI handles it.

## Alternatives considered

- A TypeScript backend would share types directly, but rewriting the tested Python backend costs
  far more than a generated contract.
- `openapi-fetch` provides the same route-typed calls as a dependency. A typed helper of about 30
  lines over the existing `request()` does the same at this API size and keeps its error handling.
- Validating responses at runtime with a schema library would catch drift only in a running page,
  not in CI.

## Consequences

A change to a response model is a two-command update (`scripts/export_openapi.py`, then
`npm --prefix web run api:types`) in the same commit. The schema also documents the HTTP API, which
is a compatibility surface, so an accidental payload change shows up in review as a diff to
`web/openapi.json`. Request bodies with a closed set of values are validated by Pydantic, so an
unknown `privacy_policy` is rejected with FastAPI's standard 422 validation detail, whose messages
the Web UI shows like any other API error.
