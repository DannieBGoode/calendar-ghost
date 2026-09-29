# Record the source event's title and time on each Audit Entry

## Context

Activity named each entry's event by reading it live from Google: one `events.get` per distinct
event on screen, four at a time, every time the table was opened or reloaded. The Event column
filled in slowly, each view spent the quota synchronization needs, and a live read can only show
what an event is called now. It could not show what an event was called when it was synchronized,
name an event deleted since, or show that an event was renamed. The earlier invariant that event
titles are never persisted in SQLite made the live read the only option.

## Decision

- Each Audit Entry records the title, time, recurrence, and cancellation of the source event the
  decision was about, as the run saw it. The run already holds that event, so recording it costs no
  provider request.
- Descriptions, locations, attendees, organizer identity, and conferencing data are still never
  persisted. Titles and times stay out of logs, incident notifications, and Managed Projections of
  Busy-Only rules.
- Titles are stored in plain text, not encrypted with the installation master key. Decrypting a
  title is cheap, but plain text keeps them searchable in SQL, and the operator accepted that anyone
  who can read the database or a backup can read the recorded titles.
- Activity shows the recorded event. When an entry recorded no event, such as a projection removed
  with its rule or a cancellation Google reported without a title, it shows the latest earlier
  recorded event of the same rule and source event. When the recorded title differs from that
  earlier one, Activity shows the event as renamed.
- Entries recorded before this change keep no event and are not backfilled; Activity shows them
  without a name. Opening an entry still reads its source event and projection live from Google,
  one entry at a time.

## Alternatives considered

- Keeping live reads and caching them in process memory would avoid persistence but still spend
  quota after every restart and could never show historical names.
- Backfilling earlier entries during Full Reconciliation would attach an event's current title to
  decisions made before a rename, presenting a name the entry never had.
- Encrypting titles at rest protects a stolen database but prevents searching titles in SQL.

## Consequences

Activity no longer calls Google to render the table, and removed rules' history keeps its event
names. The database now holds every synchronized event's title, including those of Busy-Only rules,
so it and its backups are as sensitive as the calendars themselves. Audit history still has no
retention limit, so recorded titles are kept as long as their entries, including those of removed
rules.
