import type { ReactDoctorConfig } from "react-doctor/api"

// React Doctor checks React-specific problems that ESLint does not: impure state updaters, state
// copied from props, render-time work, and accessibility. CI fails on any warning.
export default {
  blocking: "warning",
  // No score upload, share link, or crash reports leave CI. `pnpm audit` checks dependency health
  // in CI, so the supply-chain scan would only add a second remote service to the gate.
  noScore: true,
  supplyChain: { enabled: false },
  rules: {
    // ESLint owns size and complexity for every file (complexity, max-lines-per-function), so
    // these would only report the same problem twice.
    "react-doctor/no-high-complexity-react-function": "off",
    "react-doctor/no-giant-component": "off",
  },
  ignore: {
    overrides: [
      {
        // The Activity, Incidents, People, Plans, and Rule Preview tables set explicit table roles on purpose: narrow
        // screens restyle their rows with CSS display values, which drop the native table semantics
        // in some browsers.
        files: [
          "src/features/activity-table.tsx",
          "src/features/activity-incidents.tsx",
          "src/features/people-plan-details.tsx",
          "src/features/people-plans-table.tsx",
          "src/features/people-table.tsx",
          "src/features/rule-preview-table.tsx",
        ],
        rules: ["react-doctor/no-redundant-roles", "react-doctor/no-interactive-element-to-noninteractive-role"],
      },
    ],
  },
} satisfies ReactDoctorConfig
