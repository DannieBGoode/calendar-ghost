# License the Community Edition under AGPLv3 or later

Amended by [ADR 0023](0023-hosted-service-runs-the-open-codebase.md): the hosted service runs this
open codebase with no closed components, so the separate hosted boundary below no longer applies.
Amended by [ADR 0038](0038-plans-allowances-and-limits.md), with
[ADR 0028](0028-plans-apart-from-commercial-mode.md): the Hosted Service may also charge for Plans
that differ in limits and in how soon calendars sync, while a self-hosted installation keeps every
feature; see the amendment at the end.

## Context

Calendar Ghost is intended for self-hosting and privacy-conscious communities. Those communities
need to be able to inspect, modify, run, and share the software without depending on a vendor
account. The project also expects to offer a managed, multi-tenant service later.

The original MIT license is permissive and credible, but it does not require a hosted operator who
modifies the application to offer that modified source to the people using it. A license that
forbids commercial forks could protect a future hosted business, but it would no longer be
OSI-approved Open Source and would be easy to misrepresent in self-hosting forums.

## Decision

- The Community Edition is licensed under the GNU Affero General Public License, version 3 or later.
- Commercial use, including a competing hosted service, is allowed when the AGPL conditions are
  met. The project does not add a non-compete or field-of-use restriction to the software license.
- The AGPL network-source obligation is part of the product promise: a modified network version
  must offer its users the corresponding source code.
- Calendar Ghost's name, logo, ghost mark, and tagline are governed separately by
  [TRADEMARKS.md](../../TRADEMARKS.md). Trademark protection identifies the official distribution;
  it does not restrict anyone's right to use the code under the AGPL.
- The Community Edition remains a single-installation runtime. A future hosted service is a
  separate composition boundary and must receive a deliberate architecture and legal review for
  AGPL compliance, customer isolation, proprietary additions, and operational terms.
- Contributions are accepted under the published AGPL. Contributors retain copyright and must have
  the right to submit their work. There is no contributor license agreement or copyright
  assignment, so the project cannot reuse community contributions under separate proprietary terms
  without their authors' permission.
- The hosted service charges for operating Calendar Ghost, not for features. The Community Edition
  does not have features removed, limited, or held back to push people toward it.

## Consequences

Self-hosting users get a familiar OSI-approved license and can verify that the product has no
license server, telemetry requirement, or hosted control plane. A hosted competitor can exist, so
the business must compete through managed operations, support, upgrades, backups, availability,
trust, and product experience rather than an exclusive legal claim over the AGPL code.

The project must be candid that AGPL is not a no-compete license. It must also keep the source,
build instructions, notices, and network-source path usable for modified deployments. The
maintainer wrote all code in the history before the change, so the relicensing needed no other
contributor's permission; code published under MIT before the change remains available under MIT.

Without a CLA, the project gives up the option to relicense community contributions later. That is
deliberate: it is the clearest signal to self-hosting users that the license cannot be changed
against them.

## Alternatives considered

- **Keep MIT.** Rejected for the Community Edition: it offers no copyleft protection for hosted
  modifications and does not express the project's source-sharing expectation.
- **Use PolyForm, FSL, BUSL, or another no-compete/source-available license.** Rejected for the
  Community Edition: those licenses can reserve the hosted business, but they are not OSI-approved
  Open Source and would undermine the trust goal in self-hosting and privacy communities.
- **Use AGPL with an additional no-compete restriction.** Rejected: that would conflict with the
  open-source claim and the rights AGPL grants.

## Amendment: Plans (2026-10-16)

The last bullet of the decision, that the hosted service charges for operating Calendar Ghost and
not for features, reads differently now. The Hosted Service runs this same code with Plans on
([ADR 0028](0028-plans-apart-from-commercial-mode.md), as amended, and
[ADR 0038](0038-plans-allowances-and-limits.md)). Its Plans may differ in how many rules,
Connected Accounts, and Integration Tokens a User has and how soon their calendars sync, including
Instant Sync, so a Plan that costs more may allow more. They never differ in how a rule protects
privacy or in the tools to see and recover from a problem. The rest of the bullet stands for the
Community Edition: a self-hosted installation has every feature and no limits unless its own
administrator turns Plans on, and nothing is removed, limited, or held back from it to push people
toward the Hosted Service.
