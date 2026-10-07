/** One step in the "How it works" list: title and body stay strings, but a translation must
 * supply exactly three (matched by the `[Step, Step, Step]` tuple below), not more or fewer. */
interface Step {
  title: string
  body: string
}

/** One row of the Activity mockup: one event, what Calendar Ghost did about it, and why. */
interface ActivityRow {
  /** What Calendar Ghost did, in plain words, first: "Added to Work". */
  outcome: string
  /** What the source calendar showed, the reason: "New in Personal". */
  trigger: string
  /** The event, and when it happens. */
  title: string
  when: string
  /** When the sync made the decision. */
  time: string
}

// Every user-visible word on the site. A new language copies this module and
// `satisfies Messages`, so a missing key fails `astro check`. Fixed-length lists (the headline's
// two lines, the five weekdays, the five things that always stay behind, and the three "how it
// works" steps) are typed as tuples, so a translation with the wrong count also fails `astro
// check`. The tuples widen their elements back to `string` (not literal English text), so a
// translation is free to use its own words.
export const en = {
  /** The product name, shown in the nav, the footer, and the integration mockups. */
  brand: "Calendar Ghost",
  meta: {
    title: "Calendar Ghost: private calendar sync you host yourself",
    description:
      "Sync your Google calendars on your own server. Share only “Busy”, or the event's details. Open source, self-hosted, no trackers.",
    notFoundTitle: "Page not found · Calendar Ghost",
    /** A documentation page's title: `{title}` is its document's own first heading. */
    docTitle: "{title} · Calendar Ghost",
    ogImageAlt: "Calendar Ghost: Sam's calendars pass through the ghost, and the Work calendar shows Personal and Family plans only as Busy",
  },
  nav: {
    label: "Main",
    home: "Calendar Ghost home",
    howItWorks: "How it works",
    features: "Features",
    selfHost: "Self-host",
    star: "Star on GitHub",
    menu: "Menu",
    language: "Language",
    newTab: "(opens in a new tab)",
  },
  motion: {
    pause: "Pause animation",
    play: "Play animation",
    /** The same, in short, where a demo shows short words on its control (the hero's diagram, the
     * Haunted Week). */
    pauseShort: "Pause",
    playShort: "Play",
  },
  /** The nav's Light/Dark toggle (components/ThemeToggle.astro, lib/theme.ts). `current` names the
   * theme on screen out loud for assistive technology; `{state}` is filled with one of the two
   * words. */
  theme: {
    light: "Light",
    dark: "Dark",
    current: "Theme: {state}",
  },
  /** What the ghost says in its speech bubbles. Jokes only: never the only place a fact lives. */
  ghost: {
    crossingBusy: "Dentist? What dentist?",
    crossingDetails: "Title and place came along. The guest list stayed home.",
    notFound: "This page never crossed over.",
  },
  hero: {
    /** The headline, one sentence per line. */
    titleLines: ["Sync your calendars.", "Keep your privacy."] as [string, string],
    /** The one line under the headline; it keeps the self-hosting fact in the hero. */
    line: "You see everything. Work sees Busy. All on your own server.",
    primary: "Self-host it",
    secondary: "Star on GitHub",
    /** The diagram under the hero's copy (sections/Hero.astro), on Sam's Tuesday. Events travel
     * through the ghost: onto Work, Personal's and Family's arrive as “Busy” (Busy-Only
     * Projection) and Work's own client call keeps its title; onto Personal (“What you see”)
     * every title stays. The view names are `demo.workSees` and `demo.youSee`; Personal,
     * Family, and Work are `demo.calendars`; the gym session and the client call are
     * `demo.events`; the accounts are `app.rules.accounts`; the loop's Pause and Play are
     * `motion`. */
    diagram: {
      /** The column labels: over Sam's calendars, and over the day on the right in each view. */
      calendarsLabel: "Your calendars",
      dayLabels: { work: "Work calendar", you: "Personal calendar" },
      /** The family's event on Sam's Tuesday, after the hours the week shows. */
      events: { familyDinner: "Family dinner" },
      /** The mark before each event's title wherever the drawing shows it. A title hidden from
       * Work shows the ghost glyph instead. The drawing is hidden from screen readers, which
       * read the facts below without these. */
      emoji: { gym: "🏋️", clientCall: "💼", familyDinner: "🍝" },
      /** A calendar's event under its name: "Gym 12:00". */
      eventLine: "{event} {time}",
      /** The caption over the titles the ghost keeps back from Work. */
      kept: "Kept from Work",
      /** The name of the switch over the whole diagram. */
      viewLabel: "Calendar to show",
      /** The diagram's name and its facts, for screen readers; the drawing is hidden from them. */
      summary: "Sam's calendars, and what work sees of them",
      busyFact: "{event} from {from} appears on Work as Busy, from {start} to {end}.",
      ownFact: "{event}, Work's own meeting, shows with its title, from {start} to {end}.",
      never: "No titles, guests, meeting links, or invitations from Sam's other calendars reach Work.",
      youFact: "In what you see, Sam's Personal calendar, the gym session, the client call, and the family dinner all keep their titles.",
      /** The control that starts the loop over. */
      replay: "Replay",
    },
  },
  demo: {
    days: ["Mon", "Tue", "Wed", "Thu", "Fri"] as [string, string, string, string, string],
    youSee: "What you see",
    workSees: "What work sees",
    busy: "Busy",
    workCalendar: "Work calendar · sam@work.example",
    calendars: { personal: "Personal", family: "Family", work: "Work" },
    events: {
      standup: { title: "Standup", detail: "Team" },
      clientCall: { title: "Client call", detail: "Acme" },
      oneOnOne: { title: "1:1 with Lee", detail: "Room 3" },
      designReview: { title: "Design review", detail: "Team" },
      retro: { title: "Retro", detail: "Team" },
      dentist: { title: "Dentist", detail: "Smile Clinic" },
      gym: { title: "Gym", detail: "with Ana" },
      schoolDropOff: { title: "School drop-off", detail: "Maple Primary" },
      therapy: { title: "Therapy", detail: "Dr. Okafor" },
      recital: { title: "Recital", detail: "Town hall" },
    },
  },
  how: {
    title: "How it works",
    steps: [
      {
        title: "Connect your Google accounts.",
        body: "Personal, family, and work can each be a different Google account.",
      },
      {
        title: "Make a rule.",
        body: "Pick one calendar to read from and one to write to. Then choose what crosses over.",
      },
      {
        title: "Preview, then sync.",
        body: "See exactly what will be written before anything changes. Then it runs by itself every five minutes.",
      },
    ] as [Step, Step, Step],
  },
  /** The "How it works" strip's small pieces of the app, and the ghost waiting at the last step. */
  howStrip: {
    ghost: "I'll take it from here.",
    previewRule: "Preview rule",
    startSyncing: "Start syncing",
  },
  week: {
    title: "All your calendars. One week at work.",
    body: "Personal and Family plans land on your Work calendar as Busy, and stay in step when they change.",
    summary:
      "Events from the Personal and Family calendars arrive on the Work calendar as “Busy”. Work's own meetings stay as they are.",
  },
  crossing: {
    title: "You choose what crosses over.",
    switchLabel: "What crosses over",
    busyOnly: "Busy only",
    withDetails: "With details",
    busyOnlyBody: "Only the time crosses over, titled “Busy”.",
    withDetailsBody: "The title, description, and place cross over too.",
    alwaysStaysTitle: "Always stays behind",
    alwaysStays: ["Guests", "Organizer", "Meeting links", "Attachments", "Invitations"] as [
      string,
      string,
      string,
      string,
      string,
    ],
    summary:
      "The Dentist event moves from the Personal calendar to the Work calendar. With Busy only, it arrives titled “Busy”. With details, it keeps its title and place. Guests and the meeting link never cross over.",
  },
  app: {
    title: "Features",
    body: "The app's own screens, redrawn with made-up data for Sam's calendars.",
    /** The app, feature by feature: the screen it lives on, a short title, and one plain sentence. */
    features: {
      rules: {
        screen: "Rules",
        title: "As many rules as you need",
        body: "Each rule reads one calendar and writes to one other, with its own choice of Busy only or details.",
      },
      activity: {
        screen: "Activity",
        title: "Activity log",
        body: "One line per event: what Calendar Ghost did, and why.",
      },
      health: {
        screen: "Overview",
        title: "Synchronization health at a glance",
        body: "The Overview answers “is everything in sync?” in one line, and says what needs a look when something is wrong.",
      },
    },
    overview: {
      alt: "Calendar Ghost Overview: synchronization is healthy, with 3 rules running",
      headline: "Synchronization is healthy",
      detail: "Calendar Ghost checks your calendars for changes every five minutes.",
      running: "3 rules running",
      lastSync: "Last sync 2 minutes ago",
      bubbleTitle: "All good!",
      bubbleBody: "Your calendars are in sync.",
    },
    rules: {
      alt: "Calendar Ghost Rules: Family to Work and Personal to Work as Busy only, and Work to Personal with details, all enabled",
      /** One per rule, in list order: work sees Busy; Sam's own Personal calendar gets the details. */
      policies: [
        "Busy only, including all-day events",
        "Busy only, including all-day events",
        "With details, including all-day events",
      ] as [string, string, string],
      enabled: "Enabled",
      accounts: { family: "sam@family.example", personal: "sam@personal.example", work: "sam@work.example" },
      synced: ["Last synced 4 minutes ago", "Last synced 3 minutes ago", "Last synced 2 minutes ago"] as [
        string,
        string,
        string,
      ],
    },
    activity: {
      alt: "Calendar Ghost Activity: what happened to five of Sam's events, and why",
      /** Sam's week (demo/week.ts), plus two evening events the week does not show. The words
       * follow the app's Activity (web/src/lib/activity-reasons.ts), outcome first. */
      rows: [
        { outcome: "Added to Work", trigger: "New in Personal", title: "Dentist", when: "Mon 15:00–16:30", time: "09:41" },
        { outcome: "Updated in Work", trigger: "Moved from 11:00 in Personal", title: "Gym", when: "Tue 12:00–13:00", time: "09:41" },
        { outcome: "Added to Work", trigger: "New in Family", title: "School drop-off", when: "Wed 09:00–10:00", time: "09:36" },
        { outcome: "Removed from Work", trigger: "Cancelled in Personal", title: "Haircut", when: "Thu 17:30–18:00", time: "09:31" },
        { outcome: "Skipped", trigger: "Declined", title: "Book club", when: "Thu 19:00–20:30", time: "09:31" },
      ] as [ActivityRow, ActivityRow, ActivityRow, ActivityRow, ActivityRow],
    },
  },
  trust: {
    title: "Built to be trusted",
    /** Read after a claim's title by screen readers: the title links to the proof. */
    docs: "(read how, in the documentation)",
    cards: [
      {
        title: "Fixes itself",
        body: "Someone edits or deletes an event Calendar Ghost added? The next sync puts it back the way the source calendar says.",
      },
      { title: "Preview first", body: "A rule cannot start until you have seen exactly what it will write." },
      { title: "Never emails your guests", body: "Events Calendar Ghost adds never send invitations or updates to anyone." },
      {
        title: "No loops",
        body: "Events that Calendar Ghost creates are never synced again, even with rules in both directions.",
      },
      {
        title: "Recurring events stay recurring",
        body: "A weekly meeting arrives as a weekly event, with its exceptions.",
      },
      { title: "See what happened", body: "Activity shows what each rule did, and why." },
      { title: "No telemetry", body: "It talks only to Google and to the notification targets you set up." },
      {
        title: "Monitors and AI agents",
        body: "A status API and an MCP server report health to Uptime Kuma, your homelab dashboard, or your AI agent.",
      },
    ],
  },
  /** Monitors, dashboards, and AI agents reading Installation Status. Text between backticks is
   * shown as code (field names and paths stay as they are in every language). */
  integrations: {
    title: "It reports to your homelab.",
    body: "Your dashboard, your uptime monitor, and your AI agent can all ask if sync is working.",
    summary:
      "A dashboard tile shows Calendar Ghost as Healthy with 3 rules running. An uptime monitor shows it as Up, and once sent an alert when it needed a look. An AI agent asked “Is my calendar sync working?” and got the answer that all is well.",
    dashboard: {
      label: "Dashboard",
      statusLabel: "Status",
      summaryLabel: "Summary",
      healthy: "Healthy",
    },
    monitor: {
      label: "Uptime monitor",
      up: "Up",
      alerted: "Needs a look · alert sent",
    },
    agent: {
      label: "AI agent",
      /** Under the assistant's name in the chat's header: how it reaches Calendar Ghost. */
      via: "via MCP",
      question: "Is my calendar sync working?",
      answer: "Calendar Ghost is healthy: 3 rules running, last synced 2 minutes ago. Nothing needs your attention.",
    },
    /** A link to the self-hosting guide's section on tokens, the status API, and the MCP server. */
    guide: "Set up monitors and agents",
  },
  selfHost: {
    title: "Self-host it",
    /** The one line under the title. */
    line: "One Docker service and one SQLite file, on a server you own.",
    /** What you need, in one quiet line under the commands. */
    requirements: "Docker and a Google Cloud project. Runs on a Raspberry Pi.",
    copy: "Copy",
    copied: "Copied",
    selected: "Selected. Press Ctrl+C or ⌘C.",
    guide: "Read the self-hosting guide",
  },
  why: {
    title: "Why I built this",
    body: [
      "I wanted my personal and family plans to block time on my work calendar, without my employer seeing my dentist appointments, and without handing every calendar I own to yet another hosted service.",
      "The self-hosted tools I found did not work the way I needed. So I built the one I wanted: one-way rules, Busy by default, a preview before anything is written, and everything on my own machine.",
      "It is early, it is open source, and I would love your feedback.",
    ],
    signature: "Daniel (@DannieBGoode)",
  },
  faq: {
    title: "Questions",
    items: [
      { q: "Is it free?", a: "Yes. It is open source under AGPL-3.0." },
      {
        q: "Can it sync both ways?",
        a: "Yes, with two rules, one in each direction. Calendar Ghost never syncs its own events back.",
      },
      { q: "Outlook, iCloud, or CalDAV?", a: "Not yet. Google Calendar is the only provider today." },
      {
        q: "Is it ready for my real calendars?",
        a: "Yes. Like any self-hosted software, you run it at your own risk, so keep backups.",
      },
      { q: "Is there a hosted version?", a: "Not yet. If one comes, it will run this same open code." },
    ],
  },
  footer: {
    cta: "Ready when your server is.",
    body: "Free and open source. It runs on a home server, a VPS, or a Raspberry Pi.",
    tagline: "Private calendar sync you host yourself.",
    /** The footer's links, as a screen reader names them. */
    label: "About Calendar Ghost",
    projectTitle: "Project",
    legalTitle: "Legal",
    github: "GitHub",
    guide: "Self-hosting guide",
    docs: "Documentation",
    changelog: "Changelog",
    licenseLink: "AGPL-3.0 license",
    trademarks: "Trademarks",
    noTrackers: "This page has no trackers.",
    noTrackersBody: "No analytics, no cookies, nothing loaded from another site.",
    /** Under the dozing ghost on the home page's footer: narration, not speech. */
    watch: "Sync runs every five minutes. In between, the ghost naps.",
    /** What the dozing ghost mumbles in its sleep, like a child in bed: sync runs every five
     * minutes, so five more minutes is exactly its nap. */
    sleepTalk: "Five more minutes, please.",
  },
  /** The pages built from the repository's documentation (pages/docs/[slug].astro). Each page's
   * title is its document's own first heading; `pages` gives each a description for search
   * results and link previews. */
  docs: {
    pages: {
      "self-hosting": {
        description:
          "Run Calendar Ghost on your own machine: Docker, a Google Cloud project, the settings file, first-run setup, monitors and agents, and backups.",
      },
      troubleshooting: {
        description: "What to check when Calendar Ghost cannot reach Google, a rule stops, or an event did not synchronize.",
      },
    },
    /** The small table of contents beside the document. */
    contents: "On this page",
    /** The documentation home on GitHub, at the top of the contents. */
    allDocs: "All documentation",
    /** The note at the foot of each page: `{path}` is the document's path in the repository. */
    builtFrom: "This page is built from `{path}`;",
    edit: "edit it on GitHub.",
    /** The code blocks' copy button reuses `selfHost.copy`, `copied`, and `selected`. */
  },
  notFound: {
    title: "Nothing here but a ghost.",
    body: "This page does not exist. The ghost looked everywhere, then took a nap.",
    home: "Back to the home page",
  },
}

export type Messages = typeof en
