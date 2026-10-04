# Translate the Web UI through typed message catalogs

## Context

The Web UI hard-coded English throughout: components held literal strings, several sentences were
built by gluing fragments together (`` `${count} account${count === 1 ? "" : "s"} connected, ${reauthorize}` ``),
plurals were hand-written per call site, and dates, times, and numbers went through `Intl`
constructors and `toLocale*()` calls scattered across the codebase, several pinned to `"en-US"`.
The server sent English prose for error messages and Incident summaries, and the UI showed that
text as-is, so a client could not translate it even if the frontend were ready to.

Calendar Ghost is heading toward other Western, Latin-script languages (Spanish, French, German,
Portuguese, Italian, Dutch). None of those need right-to-left layout or a different script, but
all need plurals that do not match English's two forms, longer words and sentences, and
locale-correct number and date formatting.

## Decision

- **JSON catalogs per language**, one directory per language tag under `web/src/i18n/locales/<tag>/`,
  one JSON file per screen (`common`, `app`, `auth`, `overview`, `rules`, `rule-details`,
  `activity`, `settings`). English is bundled statically and is the fallback for any key missing
  from another catalog; other languages load through `import()` so Vite splits them out of the
  main bundle.
- **An in-house translator**, `createI18n({ locale, formatLocale, catalog, fallback, transform })`,
  which takes one options object (`fallback` defaults to English) and resolves dot-path keys,
  interpolates `{name}` placeholders, and selects a plural form with `Intl.PluralRules` when a
  message is an object of CLDR categories (`zero`, `one`, `two`, `few`, `many`, `other`, with
  `other` required).
- **All formatting through `i18n.format`.** Dates, times, date and time ranges, relative time,
  lists, numbers, and byte sizes go through one set of locale-bound formatters. Every prior
  `toLocale*()` call and bare `Intl` constructor moved there.
- **Language choice**: the administrator's saved choice, then the first matching
  `navigator.languages` entry (`navigator.language` when that list is empty), then English.
- **Server text stays English for now.** API error details, Incident summaries, and Installation
  Status problem summaries the UI shows stay English until a follow-up gives them codes.
  Configuration examples for other tools, such as the Integrations code blocks, are copied as is
  and never translated.
- **Diagnostics, logs, and the incident email stay English.** Provider error text, Audit Entry
  `detail`, Drift `detail`, and reconciliation conflict `detail` are shown as recorded, under a
  translated diagnostic label such as "Recorded detail."

**Why no library.** The copy needs placeholders, plural selection, and locale-aware formatting. It
does not need ICU `select`, gender, or nested rich-text beyond a handful of inline tags. A general
message-formatting library would add a runtime dependency and bundle weight for features the
product does not use. The translator's public shape, `t(key, params)` and `format.*`, is small
enough that `intl-messageformat` or a similar library could replace its internals later without
touching any call site, since call sites never parse ICU syntax themselves.

## Alternatives considered

- **A full ICU message library (`intl-messageformat`, FormatJS) from the start.** Rejected for now:
  no current message needs `select` or gender, and the added dependency and bundle weight buy
  nothing today. The translator's interface leaves room to adopt one later.
- **Server-rendered or server-chosen locale.** Rejected: the Community Edition is a single-page
  React app behind a JSON API; the server has no view layer to render, and sending a locale
  parameter on every request would couple the API to a UI concern the frontend already owns.
- **Translating diagnostics and the incident email.** Rejected: provider error text and recorded
  `detail` values are evidence for debugging and must match what the provider or the sync engine
  actually said. Translating them would risk losing precision or mismatching support instructions
  that reference the English text.

## Consequences

- Adding a language is: copy `locales/en/` to a new directory, translate the values, register
  `{ tag, load }` in `locales/index.ts`, and pass the catalog tests. No component,
  `lib/` function, or API change is needed per language.
- English is the source of truth. A key missing from another catalog falls back to English rather
  than breaking the build, but the catalog tests still require matching keys and placeholders so a
  translation cannot silently drift out of date.
- New copy must go through the catalogs: the `calendar-ghost/no-literal-ui-text` ESLint rule flags
  literal JSX text and common text attributes, the catalog tests check keys and placeholders, and
  pseudo-locale render checks fail when a visible text node is not wrapped in `t()`.
