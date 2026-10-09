# Landing page for self-hosters

Date: 2026-10-04. Status: built. Updated 2026-10-07 to describe the page as it is.

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
open source, self-hosted, and Google-only, and knows the next step: self-host it or star it on
GitHub. The page loads fast, works without JavaScript for its content, and contacts no third party.

## Decisions

- **Same repository, `site/` folder.** The page and the code live together, so stars, issues, and
  links go to one place, and one pull request can update a feature and the page that describes it.
  ADR 0023 already keeps the future Hosted Service in this open codebase. Moving the folder out later
  is cheap, so this needs no ADR.
- **Never part of the container image.** The `Dockerfile` copies only named folders, and `site` is
  in `.dockerignore`, so it does not even enter the build context.
- **Astro with React islands.** Astro builds plain static HTML with built-in i18n routing. Only the
  interactive demos load JavaScript, as React islands, the same React the Web UI uses.
- **Cloudflare builds from Git.** Workers with static assets, built by Cloudflare Workers Builds on
  pushes that touch `site/`, `docs/`, or `README.md`. Pull request branches get preview URLs. No
  deploy secrets in GitHub.
- **No star count at launch.** The repository has one star, and a button showing "1" works against
  the page. A later change adds a cached `/api/stars` Worker route when the number helps.
- **Cookieless analytics, first-party only.** Superseded "No analytics" before launch: visits,
  referrers, campaigns, and a few clicks (GitHub, the install commands, the guide) are counted with
  Umami Cloud. A small Worker serves Umami's tracker and forwards its events from
  `calendarghost.com`, so the page sets no cookies and makes no third-party request. GitHub's
  Insights → Traffic still shows what happens after the click.
- **English only at launch, built for many languages.** All copy lives in typed message files, and
  no text is baked into images or animations.
- **The ghost is the main character.** The landing page is its own register, recorded in
  `PRODUCT.md` and as the Landing Page Register Rule in `DESIGN.md`. Nothing from it enters the app.
- **New headline.** "Your busy time, everywhere it needs to be." is replaced on the page by "Sync
  your calendars. Keep your privacy." It names the action and the difference, and it translates
  cleanly. Whether the application adopts it is a separate decision.
- **One page.** The site is one landing page plus the documentation pages and the 404 page. It is
  changed in place.

### What changed since the first design, and why

The first design (this spec's first version) shipped a hero called the Wide Reveal: a full work
week under a slider whose handle was the ghost, with a chip and a sub-line over it. Before launch,
the page was redesigned by comparing alternatives side by side: two whole-page designs (`/bold`, a
louder take, and `/journey`, one story down the page) and a series of home heroes (A to E5) at
their own routes, listed on an internal index at `/versions`. Hero E5 won and became the hero at
`/`; every other version and the index were then removed. The last commit that has them all is
`ef81804`; check it out with `git worktree add ../calendar-ghost-ef81804 ef81804` to see them.

What the comparison changed:

- **The hero shows the mechanism, not a before-and-after.** The Wide Reveal asked the visitor to
  drag, and read as two similar weeks. The diagram shows events travelling through the ghost and
  what each calendar ends up with, without any input.
- **The scope chip and the long sub-line went.** One line ("You see everything. Work sees Busy.
  All on your own server.") keeps the self-hosting fact in the hero; the rest is shown, not said.
- **"Pre-alpha" went.** The FAQ says plainly that it is ready to use, at your own risk, with
  backups.
- **Headings moved from Fraunces to Besley.** Besley, a sturdy Clarendon, reads with authority at
  weight 600 and never needs tightening.
- **The app is shown as redrawn mockups**, with Sam's made-up data, instead of screenshots, so the
  page follows its own light or dark theme and shows each feature at its best.
- **A light and dark toggle**, which follows the device until pressed.
- **Decorative motion plays briefly each time it comes into view** (at most five seconds), so it
  needs no pause control; only the demos loop, each with its own Pause. A site-wide "Pause
  animations" control was tried and removed for this.
- **The self-hosting guide and troubleshooting render as pages on the site**, so the page's links
  stay on the site.

## Copy rules

- Plain, literal explanations in short active sentences; microcopy may joke.
- True to `CONTEXT.md`. The page never promises more or less than the product does: a Details
  Projection copies the title, description, and location; guests, organizer, conferencing links,
  attachments, and invitations never cross over under any rule. Plain words are fine ("Busy" for a
  Busy-Only Projection), avoided glossary terms are not.
- Honest about scope: Google Calendar only, one-way rules, run at your own risk. Never "pre-alpha".
- Demo content follows the README screenshots' fictional person, Sam, with Personal, Family, and
  Work calendars, so the animations and mockups tell one story.
- No em dashes.

## The page, in order

1. **Navigation.** Ghost mark and wordmark, How it works, Features, Self-host, the Light/Dark toggle,
   and a "★ Star on GitHub" button with no count. The language picker exists but stays hidden while
   there is one language. On phones the links collapse into a menu.
2. **Hero.**
   - Headline: "Sync your calendars." and, in Lantern Indigo, "Keep your privacy."
   - One line: "You see everything. Work sees Busy. All on your own server."
   - Buttons: "Self-host it" (primary, scrolls to Self-host) and "★ Star on GitHub".
   - The diagram under them. See The hero's diagram.
3. **How it works.** Three steps, each with a small piece of the app, joined by the path the ghost
   flies along once to the last step: "Connect your Google accounts.", "Make a rule.", and
   "Preview, then sync." A Busy only / With details switch picks what step 3's preview shows.
4. **"All your calendars. One week at work." (the Haunted Week).** Sam's Work calendar as a calm
   week. Personal and Family plans arrive in transit, with their calendar's portrait, and turn
   "Busy" as the ghost hops onto each one; Work's own meetings stay as they are.
5. **"You choose what crosses over." (the Crossing).** Sam's Dentist on Personal, with every part
   of it, beside Work's afternoon. A Busy only / With details switch; the ghost carries a copy over,
   the parts the choice leaves out fall away, and it lands on Work. What always stays behind
   (guests, organizer, meeting links, attachments, invitations) stays on the Personal card.
6. **Features.** The app's Rules, Activity, and Overview screens, redrawn with made-up data for
   Sam, one feature each with a short title and one sentence, on alternating sides.
7. **Built to be trusted.** Eight short claims, each true today and each linking to the
   documentation that proves it: fixes itself, preview first, never emails your guests, no loops,
   recurring events stay recurring, see what happened, no telemetry, monitors and AI agents.
8. **"It reports to your homelab."** One sentence, three small pictures (a dashboard tile, an
   uptime monitor, and an AI agent's chat over MCP), the night watch (a ghost by a rack ticking its
   checklist in time with the monitor), and one link to the guide's section on monitors and agents.
9. **Self-host it.** One line, the three commands that are true today in one block with one Copy
   button, what you need in one quiet line, and "Read the self-hosting guide".
10. **Why I built this.** A short signed note from the administrator.
11. **Questions.** Is it free; can it sync both ways; Outlook, iCloud, or CalDAV; is it ready for my
    real calendars; is there a hosted version.
12. **Footer.** A last call to action ("Ready when your server is."), the dozing ghost that
    mumbles "Five more minutes, please.", links under Project and Legal (GitHub, the self-hosting
    guide, documentation, changelog, the AGPL-3.0 license, trademarks), and "This page has no
    trackers."

Other pages:

- **`/docs/<slug>`.** `docs/self-hosting.md` and `docs/troubleshooting.md`, rendered at build time
  from the repository's `docs/` folder with Astro's own Markdown processor. Headings keep GitHub's
  anchors; links between rendered documents stay on the site and every other repository link goes
  to GitHub. Each page has a contents list, a Copy button on every code block, and a note saying
  which file it is built from, with a link to edit it.
- **404.** A worried ghost that gives up and naps, a short joke, and a link home.

## The hero's diagram

Sam's Tuesday, read left to right (top to bottom on phones):

- **Your calendars.** Sam's Personal, Work, and Family calendars as pills with Sam's portraits, each
  with its one event: Gym 12:00, Client call 14:30, Family dinner 18:00. Work has its own calm red.
- **The ghost** at the hub, pleased as each event passes through.
- **A short day** on the right: Sam's Work calendar.

A chip with the event's title leaves each calendar along a hairline, which brightens as it passes.
Bound for Work, the gym session and the family dinner lose their titles at the ghost, which keeps
them back (shown under it as "Kept from Work"), and leave as indigo "Busy" chips; Work's own client
call keeps its title. Each lands in the day at its time, the day rests, and the cycle starts again
(about ten seconds). An emoji stands before every title the drawing shows; the ghost's own glyph
stands wherever a title is hidden from Work.

A switch over the diagram, "What work sees" / "What you see", turns the day into Sam's Personal
calendar, where every title is kept and nothing is held back. A small labelled Pause and Replay sit
in the diagram's corner.

The geometry and timing are worked out at build time and the motion is CSS, so the diagram moves
without a script. Without JavaScript, or with reduced motion, it stands still with everything
landed, as work sees it. Screen readers get the same facts as a list; the drawing is hidden from
them.

## Motion and accessibility

- Only `transform` (including motion paths) and `opacity` animate. No bounce or elastic easing.
- The demos that loop or run (the hero's diagram, the Haunted Week, the Crossing) each have a
  visible Pause control (WCAG 2.2.2) and hold while off screen.
- Every other moving thing (the idling ghosts, the How it works flight, the night watch) plays for
  at most five seconds each time it comes into view, then settles, and plays again on the next
  visit.
- `prefers-reduced-motion` stops everything that moves by itself: each demo shows its final state.
- Without JavaScript every section's text is there and each demo shows its final state.
- WCAG 2.2 AA, like the application: 4.5:1 text contrast in both themes, 44px touch targets, no
  sideways scrolling at 320px.

## Brand

- The ghost mark and the Twilight tokens for light and dark. Headings in Besley, text in Figtree,
  both self-hosted through `@fontsource-variable` packages. No Google Fonts request.
- The page follows the device's light or dark setting until the visitor presses the toggle, which
  remembers the choice. Every demo is designed for both.
- The Quiet Indicator Rule is relaxed for the page, but Lantern Indigo still marks the primary action.
- `site/src/styles/tokens.css` copies the subset of tokens the page needs, with a comment naming
  `DESIGN.md` as the source of truth.
- Calendars and accounts always show Sam's portraits, never letters in circles.

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
  `npx wrangler deploy`, build watch paths `site/**`, `docs/**`, and `README.md`. Non-production
  branches get preview URLs.
- `calendarghost.com` is the custom domain. `www.calendarghost.com` redirects to it with a
  Cloudflare redirect rule. `app.calendarghost.com` stays free for the Hosted Service.
- No server code.

## Search and sharing

Title and description per page, canonical URL, an Open Graph image for Reddit and Hacker News
previews, `sitemap.xml` (the home page and the documentation pages), `robots.txt`, and the favicon.

## Repository layout

```text
site/
  package.json, astro.config.mjs, tsconfig.json, wrangler.jsonc
  public/                 favicon, Open Graph image, robots.txt
  src/pages/              index.astro, 404.astro, docs/[slug].astro
  src/sections/           one Astro component per page section
  src/islands/            the React islands: the hero's controls, the Haunted Week, the Crossing,
                          How it works' switch, and the ghost
  src/demo/               Sam's week and each demo's data and geometry, with tests
  src/mockups/            the app's screens, redrawn
  src/docs/               which repository documents render as pages, and their link rewriting
  src/i18n/               en.ts and the typed message contract
  src/styles/             tokens, global styles, and the demos' and the ghost's styles
  e2e/                    the Playwright tests for the built page
```

- `.dockerignore` has `site`.
- `AGENTS.md` has a short `site/` section: its register, its own toolchain, the no-tracker and
  no-third-party-request rule, copy in message files only, and glossary truth.
- `tests/test_ubiquitous_language.py` also searches `site/src`, with `.astro` among the suffixes.
- `.github/workflows/site.yml`, limited to `site/**`, `docs/**`, and `README.md`, runs `npm ci`,
  `npm audit --audit-level=high`, `astro check`, the unit tests, the build and its audit, and the
  Playwright tests.

## Launch dependency: a published image

There is no published container image today: `docker-compose.yml` builds from source and the CI
Docker job does not push. The Self-host section therefore shows the steps that are true now
(`git clone`, `cp .env.example .env`, `docker compose up -d --build`). Self-hosting communities
expect an `image:` line. Publishing a multi-architecture image to GitHub Container Registry is a
separate change, recommended before the page is shared; the Self-host section then switches to a
compose file that uses it.

## Acceptance

- The hero's headline, line, calls to action, and the diagram's switch fit the first screen on a
  1280×800 and a 1024×768 screen, and the headline and primary call to action on a 390×844 phone.
- Lighthouse performance, accessibility, best practices, and SEO each score at least 95 on the
  production build.
- The built page makes no request to any host other than `calendarghost.com`.
- With JavaScript off, every section's text and the mockups are present.
- With reduced motion on, nothing moves by itself.
- A change under `site/` does not change the Docker build context or the image contents.

## Out of scope

The Hosted Service and pricing, the live star count, languages other than English, a
blog or comparison pages, and adopting the new headline inside the application.

## Open items for the administrator

- Configure Workers Builds, the custom domain, and the `www` redirect rule in Cloudflare.
- Decide whether to publish the container image before sharing the page.
