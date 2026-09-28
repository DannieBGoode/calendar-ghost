# Request basic profile for Connected Account identity

## Context

Directional Sync Rules can span several Connected Accounts. The Calendar scopes identify an account
only by its primary calendar address and cannot provide a profile name or photo, so every account
appeared as similar initials and administrators could not tell identities apart at a glance.

## Decision

Request `openid` and `https://www.googleapis.com/auth/userinfo.profile` alongside the Calendar
scopes. Read the `name` and `picture` claims from the ID token returned by Google's token endpoint
and persist only the display name and an HTTPS photo URL on the Connected Account. The profile
scopes are optional: a grant without them still connects, and the interface falls back to
initials. Calendar scopes remain the only permissions that authorize synchronization.

## Alternatives considered

- Keep Calendar-only scopes and color-code initials: preserves the narrowest grant but does not
  show recognizable identities.
- Call the People API: requires the same profile consent plus another network call during
  authorization.
- Proxy or cache photos locally: avoids browser requests to Google but adds storage and an
  image-serving route for a household utility.

## Consequences

The consent screen lists basic profile access, which Google classifies as non-sensitive.
Accounts connected before this change keep initials until they are reauthorized. The browser loads
photos directly from Google without a referrer. The `connected_accounts.avatar_url` column is added
by migration 2; earlier releases ignore it, so rolling back does not require a downgrade script.
