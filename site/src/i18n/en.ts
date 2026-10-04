// Every user-visible word on the site. A new language copies this module and
// `satisfies Messages`, so a missing key fails `astro check`.
export const en = {
  meta: {
    title: "Calendar Ghost: private calendar sync you host yourself",
    description:
      "Sync your Google calendars on your own server. Share only “Busy”, or the details you choose. Open source, self-hosted, no trackers.",
    notFoundTitle: "Page not found · Calendar Ghost",
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
  },
  hero: {
    chip: "Pre-alpha · Open source (AGPL) · Google Calendar",
    title: "Sync your calendars. Keep your privacy.",
    sub: "Calendar Ghost copies events from one Google calendar to another, on your own server. You choose what crosses over. Guests and meeting links always stay behind.",
    primary: "Self-host it",
    secondary: "Star on GitHub",
  },
  demo: {
    days: ["Mon", "Tue", "Wed", "Thu", "Fri"],
    youSee: "What you see",
    workSees: "What work sees",
    busy: "Busy",
    sliderLabel: "Compare your week with what work sees",
    sliderValueText: "{percent}% of the week shows your view",
    hint: "Drag the ghost.",
    revealSummary:
      "Sam's work week, twice. On the left, Sam sees work meetings and personal plans with their details. On the right, work sees the same meetings, and each personal plan only as “Busy”.",
    workCalendar: "Work calendar · sam@work.example",
    calendars: { personal: "Personal", family: "Family", work: "Work" },
    from: { personal: "from Personal", family: "from Family" },
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
    ],
  },
  week: {
    title: "One week, every calendar.",
    body: "Make one rule per calendar: Personal to Work, Family to Work. Calendar Ghost keeps them all in step.",
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
    alwaysStays: ["Guests", "Organizer", "Meeting links", "Attachments", "Invitations"],
    guests: "Dr. Ruiz",
    link: "meet.google.com/abc-defg-hij",
    summary:
      "The Dentist event moves from the Personal calendar to the Work calendar. With Busy only, it arrives titled “Busy”. With details, it keeps its title and place. Guests and the meeting link never cross over.",
  },
  app: {
    title: "See the app",
    body: "Real screens, with made-up data for Sam's three calendars.",
    overview: {
      alt: "Calendar Ghost Overview showing healthy synchronization, rules, and recent changes",
      caption: "Overview: one plain answer to “is everything in sync?”",
    },
    rules: {
      alt: "Calendar Ghost Rules showing source and destination calendars",
      caption: "Rules: each one reads one calendar and writes one other.",
    },
    activity: {
      alt: "Calendar Ghost Activity showing what each rule did",
      caption: "Activity: what happened to each event, and why.",
    },
  },
  trust: {
    title: "Built to be trusted",
    cards: [
      {
        title: "Fixes itself",
        body: "Someone edits or deletes a synced event? The next sync puts it back the way the source calendar says.",
      },
      { title: "Preview first", body: "A rule cannot start until you have seen exactly what it will write." },
      { title: "Never emails your guests", body: "Synced events never send invitations or updates to anyone." },
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
  selfHost: {
    title: "Self-host it",
    body: "Calendar Ghost runs as one small Docker service with one SQLite file. You own the server, the data, and the keys.",
    needsTitle: "What you need",
    needs: [
      "Docker with Compose",
      "A Google Cloud project, for sign-in with Google",
      "Any small machine: a home server, a VPS, or a Raspberry Pi (arm64)",
    ],
    stepsTitle: "Start it",
    steps: [
      "Get the code.",
      "Create your settings file, then fill it in as the guide shows.",
      "Start it, then open http://localhost:8000.",
    ],
    copy: "Copy",
    copied: "Copied",
    selected: "Selected. Press Ctrl+C or ⌘C.",
    oauthNote: "Creating the Google sign-in client is the longest step. The guide walks you through it.",
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
      { q: "Is it free?", a: "Yes. It is open source under AGPL-3.0. You run it and pay only for your own server." },
      {
        q: "Can it sync both ways?",
        a: "Yes, with two rules, one in each direction. Calendar Ghost never syncs its own events back.",
      },
      { q: "Outlook, iCloud, or CalDAV?", a: "Not yet. Google Calendar is the only provider today." },
      {
        q: "Is it ready for my real calendars?",
        a: "Not yet. It is pre-alpha: use test calendars and keep backups.",
      },
      { q: "Is there a hosted version?", a: "Not yet. If one comes, it will run this same open code." },
    ],
  },
  footer: {
    cta: "Ready to try it?",
    license: "Open source under the GNU AGPL, version 3 or later.",
    trademarks: "Trademarks",
    github: "GitHub",
    noTrackers: "This page has no trackers.",
  },
  notFound: {
    title: "Nothing here but a ghost.",
    body: "This page does not exist. The ghost looked everywhere, then took a nap.",
    home: "Back to the home page",
  },
}

export type Messages = typeof en
