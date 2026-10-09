# Users, Installation Administrators, and registration

Builds on [ADR 0023](0023-hosted-service-runs-the-open-codebase.md) and
[ADR 0029](0029-isolate-users-in-one-sqlite-database.md).

## Context

A household installation and the Hosted Service both need several people on one installation, each
with private rules, and someone who can operate it and help when something breaks, without that
person reading anyone else's calendars. Today the installation knows one administrator, identified
by a password alone.

## Decision

- **The User owns data.** Every Connected Account, rule, token, incident, and Audit Entry belongs to
  one User. A rule and both of its Connected Accounts belong to the same User. Sharing calendars
  between people stays in the calendar provider. Two Users may connect the same calendar-service
  identity; each gets their own Connected Account, and uniqueness is per User so neither can learn
  of the other's.
- **Installation Administrator is a role**, held first by the first User, grantable to others, and
  never removable from the last holder while anyone else remains. An administrator's own rules are
  as private as anyone's. The last User, who is always an administrator, may delete themself: the
  installation then returns to setup, with the Registration Policy back at Only Me and every
  pending Invitation revoked, so nobody can join an installation without an administrator.
- **The Operator Overview** shows each User's Installation Status with calendars only by neutral
  labels, plus the User's email, plan, last sign-in, state, and resource use. It is the same on
  every installation, with no setting to reveal more, and every User can see exactly what it shows
  about them.
- **Registration Policy** is Only Me by default, Invitation Only, or Open. Under Only Me, which
  new and upgraded installations start with, nobody can join, and the Web UI hides Users,
  Invitations, Plans, and the Operator Overview. An Installation Administrator may switch to
  Invitation Only or Open at any time, but back to Only Me only while no other User exists. Data
  is always User-scoped whatever the policy; the policy only decides who may join and what the Web
  UI shows. Open requires the installation to send email for verification and password reset, and
  is aimed at the Hosted Service, so it arrives with sign-up in a later phase; self-hosted
  installations add people by invitation. Invitations and Password Reset Links are single-use,
  expire after 7 days, and never let an administrator see or set a password.
- **Users sign in with email and password.** Under Invitation Only, an email is not verified,
  because the administrator vouched for the person and the installation may not send email.
- **Upgrading** turns the existing administrator into the first User, with the role and every
  existing record, and no email. Until that User adds one, sign-in accepts the password alone; the
  first sign-in after upgrading requires adding an email, after which password-only sign-in ends.

- **Integration Tokens belong to a User.** Their `status:read` scope returns that User's
  Installation Status at the same routes and in the same shape, over the status API and MCP alike.
  A new `installation:read` scope, available only to Installation Administrators, returns
  Installation Health. Upgrading gives every existing token to the first User with both scopes, so
  existing monitors keep receiving the answer they received before.
- **Incident Notifications go to the owning User**, in the Web UI and by email when the installation
  sends email. The installation's configured SMTP recipient and webhook receive only installation
  incidents, the first of which is a scheduler that stopped completing passes, so the channels an
  existing installation configured keep alerting on the condition every User shares. Users cannot configure their own webhooks yet, which keeps the installation from
  sending requests to addresses a User chooses.

- **Disabling and deleting.** An Installation Administrator may disable a User, which stops sign-in
  and holds their rules without removing anything. User Deletion runs Rule Removal for each of the
  User's rules, then removes their Connected Accounts and every record they own. A User deleting
  themself chooses whether their projections are deleted or kept; an administrator deleting
  another User always deletes them, since that User is not there to choose.
- **User Deletion removes the User from the live database only.** A backup taken before it keeps
  their records until the backup rotates out, as clearing Activity already does, and the privacy
  documentation says so.

## Amendment: Only Me (2026-10-09)

The first design made Invitation Only the default. A household installation that one person runs
then showed Users and Invitations it does not need, so Only Me became the default and the first
value. It changes only who may join and what the Web UI shows; isolation does not depend on it.
The same review moved Open, with sign-up and email verification, to the phase that builds sign-up,
because only the Hosted Service needs it.

## Considered Options

- **A household or workspace as owner.** It suits shared family calendars, but adds membership and
  roles per workspace, and gives every Hosted Service customer a one-person workspace. A workspace
  can be added above the User later without splitting records.
- **An Operator Overview that shows calendar names, or a setting to choose.** Names can be personal,
  and a setting would let critics ask which one the Hosted Service runs. One visible behavior is a
  promise anyone can verify in the code.
- **Administrator-created accounts with administrator-set passwords.** An invitation link is as fast
  and keeps passwords known only to their User.
- **A data key per User, destroyed on deletion.** It would only make old backups unreadable if the
  key were kept out of them, but a backup holds the wrapped key and the documented backup set holds
  the Installation Master Key that unwraps it. Keeping per-User keys in a store outside backups
  would make every restore lose credentials, which is more complexity than the promise is worth.
- **Usernames instead of email.** Friendlier for children, but Open registration needs email anyway,
  which would leave two identifiers.
