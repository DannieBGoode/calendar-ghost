# Landing page for self-hosters

Date: 2026-10-04. Status: proposed.

## Why

Calendar Ghost has no public face beyond its README. The administrator will share the project with
self-hosting communities (r/selfhosted, Hacker News, selfh.st) to see whether it gets traction, and
needs a page that explains in a few seconds, in very simple words, what the app does and why it is
different. The page covers self-hosting only. A later change adapts it for the Hosted Service.

Competitors set the bar. keeper.sh has clear copy and first-class self-hosting, but its hero does not
show the sync. calendarpipe.com shows a real event being transformed, but it is closed source and
asks visitors to trust it. No one shows privacy happening. Calendar Ghost's ghost already means "the
shape crosses over, the details stay behind," so the hero shows exactly that.

**Success:** a visitor understands what Calendar Ghost does from the hero alone, sees that it is
open source, self-hosted, pre-alpha, and Google-only, and knows the next step: self-host it or star
it on GitHub. The page loads fast, works without JavaScript for its content, and contacts no third
party.

## Decisions taken while designing

- **Same repository, `site/` folder.** The page and the code live together, so stars, issues, and
  links go to one place, and one pull request can update a feature and the page that describes it.
  ADR 0023 already keeps the future Hosted Service in this open codebase. Moving the folder out later
  is cheap, so this needs no ADR.
- **Never part of the container image.** The `Dockerfile` copies only named folders, and `site` is
  added to `.dockerignore` so it does not even enter the build context.
- **Astro with React islands.** Astro builds plain static HTML with built-in i18n routing. Only the
  three interactive demos load JavaScript, as React islands, the same React the Web UI uses.
- **Cloudflare builds from Git.** Workers with static assets, built by Cloudflare Workers Builds on
  pushes that touch `site/`. Pull request branches get preview URLs. No deploy secrets in GitHub.
- **No star count at launch.** The repository has one star, and a button showing "1" works against
  the page. A later change adds a cached `/api/stars` Worker route when the number helps.
- **No analytics.** Traction is read from Cloudflare's server-side traffic numbers and GitHub's
  Insights → Traffic. The page loads no tracking script and makes no third-party request.
- **English only at launch, built for many languages.** All copy lives in typed message files, and
  no text is baked into images or animations.
- **The ghost is the main character.** The landing page is its own register, recorded in
  `PRODUCT.md` and as the Landing Page Register Rule in `DESIGN.md`. Nothing from it enters the app.
- **New headline.** "Your busy time, everywhere it needs to be." is replaced on the page by "Sync
  your calendars. Keep your privacy." It names the action and the difference, and it translates
  cleanly. Whether the application adopts it is a separate decision.

## Copy rules

- Plain, literal explanations in short active sentences; microcopy may joke.
- True to `CONTEXT.md`. The page never promises more or less than the product does: a Details
  Projection copies the title, description, and location; guests, organizer, conferencing links,
  attachments, and invitations never cross over under any rule. Plain words are fine ("Busy" for a
  Busy-Only Projection), avoided glossary terms are not.
- Honest about scope: pre-alpha, Google Calendar only, one-way rules.
- Demo content follows the README screenshots' fictional person, Sam, with Personal, Family, and
  Work calendars, so the animations and screenshots tell one story.
- No em dashes.

## Page outline

1. **Navigation.** Ghost mark and wordmark, How it works, Features, Self-host, and a "★ Star on
   GitHub" button with no count. The language picker exists but stays hidden while there is one
   language. On mobile, the links collapse into a menu.
2. **Hero ("The Wide Reveal").**
   - Chip: "Pre-alpha · Open source (AGPL) · Google Calendar".
   - Headline: "Sync your calendars. Keep your privacy."
   - Sub-line: "Calendar Ghost copies events from one Google calendar to another, on your own
     server. You choose what crosses over. Guests and meeting links always stay behind."
   - Buttons: "Self-host it" (primary, scrolls to Self-host) and "★ Star on GitHub".
   - Demo: a full-width work week with a before-and-after slider whose handle is the ghost. See
     Interactive demos.
3. **How it works.** Three steps:
   1. "Connect your Google accounts." Personal, family, and work can each be a different account.
   2. "Make a rule." Pick one calendar to read from and one to write to, and choose what crosses
      over.
   3. "Preview, then sync." See exactly what will be written before anything changes. Then it runs
      by itself every five minutes.
4. **One week, every calendar ("The Haunted Week").** "Make one rule per calendar: Personal to
   Work, Family to Work. Calendar Ghost keeps them all in step."
5. **You choose what crosses over ("The Crossing").** A Busy only / With details switch beside the
   demo, and a plain list of what always stays behind: guests, organizer, meeting links,
   attachments, and invitations.
6. **See the app.** The Overview, Rules, and Activity screenshots from `docs/assets`, one sentence
   each, in the light or dark version that matches the page.
7. **Built to be trusted.** A grid of short cards, each one true today:
   - **Fixes itself.** Someone edits or deletes a synced event? The next sync puts it back the way
     the source says.
   - **Preview first.** A rule cannot start until you have seen what it will write.
   - **Never emails your guests.** Synced events never send invitations or updates.
   - **No loops.** Events Calendar Ghost creates are never synced again, even with rules in both
     directions.
   - **Recurring events stay recurring.** A weekly event arrives as a weekly event.
   - **See what happened.** Activity shows what each rule did and why.
   - **No telemetry.** It talks only to Google and to the notification targets you configure.
   - **Monitors and AI agents.** A status API and an MCP server report health to Uptime Kuma,
     homelab dashboards, or your AI agent.
8. **Self-host it.** What you need (Docker with Compose, a Google Cloud project for sign-in, any
   small machine including a Raspberry Pi on arm64), the three commands that are true today with a
   Copy button each, and a link to the self-hosting guide. It says plainly that creating the Google
   OAuth client is the longest step. See Launch dependency.
9. **Why I built this.** A short signed note from the administrator. Draft below.
10. **FAQ.**
    - *Is it free?* Yes. It is open source under AGPL-3.0. You run it and pay only for your own
      server.
    - *Can it sync both ways?* Yes, with two rules, one in each direction. Calendar Ghost never
      syncs its own events back.
    - *Outlook, iCloud, or CalDAV?* Not yet. Google Calendar is the only provider today.
    - *Is it ready for my real calendars?* Not yet. It is pre-alpha: use test calendars and keep
      backups.
    - *Is there a hosted version?* Not yet. If one comes, it will run this same open code.
11. **Footer.** A last "Self-host it" call to action, the license, a link to `TRADEMARKS.md`,
    GitHub, and "This page has no trackers."
12. **404 page.** The sleeping ghost, a short joke, and a link home.

### "Why I built this" draft

To be completed by the administrator with one or two concrete details (what was tried first, the
moment that started the project). Claims marked ⟨confirm⟩ must be checked before launch.

> I wanted my personal and family plans to block time on my work calendar, without my employer
> seeing my dentist appointments, and without handing every calendar I own to yet another hosted
> service. The self-hosted tools I found ⟨confirm: copied more than I wanted, or did not work the
> way I needed⟩. So I built the one I wanted: one-way rules, Busy by default, a preview before
> anything is written, and everything on my own machine. It is early, it is open source, and I
> would love your feedback.
>
> Daniel (@DannieBGoode)

## Interactive demos

All three share one demo data module: Sam's work week (Monday to Friday, 9:00 to 17:00) with work
events (Standup, Client call, 1:1 with Lee, Design review, Retro) and personal and family events
(Dentist, Gym, School drop-off, Therapy, Recital). Titles and labels come from the message file.
Layout math (event position from day and time) is a pure function with unit tests.

- **The Wide Reveal (hero).** Two layers of the same week. "What you see" shows work events and
  personal events with their details. "What work sees" shows the same work events unchanged and each
  personal event as a dashed "Busy" block. The top layer is clipped at the slider position, so the
  work events never change as the ghost passes and only personal events turn into "Busy". The ghost
  sweeps by itself and follows the pointer or a drag. Below 640px the week shows Monday to
  Wednesday.
- **The Haunted Week.** The work week alone. Personal and family events slide in, tagged with their
  source calendar. The ghost flies across and each one becomes "Busy" as it passes. Work events stay.
  Then the loop resets.
- **The Crossing.** One event close up. The ghost lifts "Dentist" from Personal and carries it to
  Work. With Busy only, the title, place, guests, and meeting link fade out together as it crosses,
  and it lands as "Busy". With details, the title and place stay and only guests and the meeting link
  fade out.
- **The ghost's eyes** follow the pointer in every demo.

### Motion and accessibility

- CSS animations and `requestAnimationFrame`, as in the approved mockups. Motion (the library) is
  added only if an interaction needs springs.
- Loops run only while their demo is on screen and the tab is visible, and the auto sweep pauses on
  hover, focus, or drag.
- `prefers-reduced-motion` stops every loop: the hero rests with the slider at 55% and stays
  draggable, The Haunted Week shows its finished state, and The Crossing shows its result for the
  selected switch position.
- The hero slider is a real range input ("Compare your week with what work sees") so it works with
  a keyboard and screen readers. Each demo has a text summary for assistive technology, and every
  section's content is readable without JavaScript.
- WCAG 2.2 AA, like the application.

## Brand

- The ghost mark, the Twilight tokens for light and dark, and Fraunces and Figtree self-hosted
  through the same `@fontsource-variable` packages as `web/`. No Google Fonts request.
- The page follows the device's light or dark setting. Every demo is designed for both.
- The Quiet Indicator Rule is relaxed for the page, but Lantern Indigo still marks the primary action.
- `site/src/styles/tokens.css` copies the subset of tokens the page needs, with a comment naming
  `DESIGN.md` as the source of truth. Screenshots are imported from `docs/assets` so the page and
  the README never drift.

## Languages

Astro's i18n routing with `defaultLocale: "en"` and no prefix for English, so a second language is
served at `/es/` and so on. Each language is one typed message module; a module missing a key fails
the type check. `hreflang` alternates and the hidden language picker activate automatically when a
second language exists.

## Hosting and deployment

- Cloudflare Workers with static assets. `site/wrangler.jsonc` names the Worker, points `assets` at
  the build output, and serves the 404 page for unknown paths.
- Workers Builds, configured once in the Cloudflare dashboard by the administrator: repository
  connected, root directory `site`, build command `npm ci && npm run build`, deploy command
  `npx wrangler deploy`, build watch paths `site/*`. Non-production branches get preview URLs.
- `calendarghost.com` is the custom domain. `www.calendarghost.com` redirects to it with a
  Cloudflare redirect rule. `app.calendarghost.com` stays free for the Hosted Service.
- No server code at launch.

## Search and sharing

Title and description per page, canonical URL, an Open Graph image of the hero for Reddit and
Hacker News previews, `sitemap.xml`, `robots.txt`, and the favicon.

## Repository changes

```text
site/
  package.json, astro.config.mjs, tsconfig.json, wrangler.jsonc
  public/                 favicon, Open Graph image, robots.txt
  src/pages/              index.astro, 404.astro
  src/sections/           one Astro component per page section
  src/islands/            WideReveal, HauntedWeek, Crossing (React)
  src/demo/               Sam's week and the layout functions, with tests
  src/i18n/               en.ts and the typed message contract
  src/styles/             tokens.css, global.css
```

- `.dockerignore` gains `site`.
- `AGENTS.md` gains a short `site/` section: its register, its own toolchain, the no-tracker and
  no-third-party-request rule, copy in message files only, and glossary truth.
- `tests/test_ubiquitous_language.py` also searches `site/src`, with `.astro` added to the suffixes.
- A `.github/workflows/site.yml` workflow, limited to `site/**`, runs `npm ci`,
  `npm audit --audit-level=high`, `astro check`, the unit tests, and the build.

## Launch dependency: a published image

There is no published container image today: `docker-compose.yml` builds from source and the CI
Docker job does not push. The Self-host section therefore shows the steps that are true now
(`git clone`, `cp .env.example .env`, `docker compose up -d --build`). Self-hosting communities
expect an `image:` line. Publishing a multi-architecture image to GitHub Container Registry is a
separate change, recommended before the page is shared; the Self-host section then switches to a
compose file that uses it.

## Acceptance

- The hero explains the product without scrolling on a 1280×800 screen and on a 390×844 phone.
- Lighthouse performance, accessibility, best practices, and SEO each score at least 95 on the
  production build.
- The built page makes no request to any host other than `calendarghost.com`.
- With JavaScript off, every section's text and the screenshots are present.
- With reduced motion on, nothing moves by itself.
- A change under `site/` does not change the Docker build context or the image contents.

## Out of scope

The Hosted Service and pricing, the live star count, languages other than English, analytics, a
blog or comparison pages, and adopting the new headline inside the application.

## Open items for the administrator

- Complete "Why I built this" and confirm its marked claim.
- Configure Workers Builds, the custom domain, and the `www` redirect rule in Cloudflare.
- Decide whether to publish the container image before sharing the page.
