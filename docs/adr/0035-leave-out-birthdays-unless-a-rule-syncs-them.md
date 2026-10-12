# Leave out birthdays unless a rule syncs them

Builds on [ADR 0018](0018-project-by-invitation-response.md), whose exclusions this one joins.

## Context

Google keeps a user's contacts' birthdays among the events of their primary calendar. Each is a
yearly all-day series that `events.list` returns with `eventType: "birthday"`. Google Calendar's
sidebar lists "Birthdays" as if it were a separate calendar, but it only shows or hides those
events. Rules read every event of their Source Calendar, so a rule from a primary calendar projected
every contact's birthday, and users did not expect it.

## Decision

- The Google adapter reads `eventType: "birthday"` as a birthday on the domain's Calendar Event.
  Every other event type, such as out of office or focus time, is read as before.
- A **Birthday Policy** joins the Transformation Policy: `exclude` (the default) projects no
  birthday, and `include` projects birthdays like other events. Changing it is a Material Rule
  Change. Users see it as "Sync birthdays".
- An excluded birthday is an exclusion, decided like the all-day and invitation-response ones: an
  unmapped one is skipped (`birthday`) and a mapped one has its projection deleted
  (`birthday_removed`). It is checked before the all-day exclusion, because it is the more specific
  reason.
- Migration 30 gives existing rules the default and sets their reprojection flag, so the next run
  removes the birthdays they projected.

## Alternatives considered

- A separate "Birthdays" calendar made up from the primary calendar, as Google Calendar's sidebar
  shows it. Google has no identifier for it, so every adapter call would translate a made-up calendar
  back into the primary calendar and a filter, it could only ever be a source, and the primary
  calendar would still have to leave birthdays out. A rule setting gives the same choice. The
  birthday marker this decision adds would still serve such a calendar later.
- Asking Google for every other event type with `eventTypes`. A mapped birthday would then never be
  listed again, so its projection could not be removed, and no rule could choose to sync birthdays.
- Always leaving birthdays out. Some users want them in the destination.

## Consequences

Upgrading deletes the projections of birthdays on each rule's next run, without a new preview.
Activity records each as `birthday_removed`. A rule that should keep them must be edited to sync
birthdays, previewed, and enabled again. Rolling back to an earlier release keeps the column but
ignores it, and that release projects birthdays again on its next full pass.
