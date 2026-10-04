# Licensing and editions

## Community Edition

The code in this repository is the Calendar Ghost Community Edition. It is genuine open-source
software under the [GNU Affero General Public License, version 3 or later](../LICENSE), an
OSI-approved copyleft license.

AGPL permits personal, internal, self-hosted, and commercial use. It also permits a competing
service when the license conditions are met. In particular, a modified version offered over a
network must give its users an opportunity to receive the corresponding source code. An open-source
license cannot forbid commercial forks while remaining an OSI-approved open-source license; that
restriction would make the project source-available instead.

The Community Edition is single-installation and single-administrator: one SQLite database, one
scheduler, and one application process per installation. It does not require a Calendar Ghost
account, hosted coordinator, license server, or paid subscription.

The AGPL does not grant rights to use the Calendar Ghost name, logo, ghost mark, or tagline. See
[TRADEMARKS.md](../TRADEMARKS.md) for the project's branding policy.

## Hosted service

The future hosted service runs the code in this repository for people who do not want to operate it
themselves. It has no closed components and no private fork: billing, plans, and the operator
overview will be public code in this repository, so anyone can read what the hosted service runs.

Billing and plan limits only apply when Commercial Mode is on, and it is off by default. On a
self-hosted installation, every user has every feature, and no billing code contacts a payment
provider. The hosted service charges for operating Calendar Ghost, not for features: the Community
Edition will not have features removed, limited, or held back to push people toward it. See
[ADR 0023](adr/0023-hosted-service-runs-the-open-codebase.md).

## Contributions

Contributions are welcome under the AGPL. Contributors retain copyright in their work and must have
the right to submit it under the published license. There is no contributor license agreement (CLA)
and no copyright assignment, so community contributions cannot be relicensed under other terms
without their authors' permission.

## License history

Calendar Ghost was first published under the MIT License. Version 0.1.0 and the code published
before the change to the AGPL on 2026-10-02 remain available under the MIT License. The maintainer
wrote all code in the history up to that change, so the change needed no other contributor's
permission.

This document explains project intent and is not legal advice; the text in
[`LICENSE`](../LICENSE) controls.
