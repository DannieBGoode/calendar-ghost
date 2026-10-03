import type { ReactDoctorConfig } from "react-doctor/api"

// React Doctor checks React-specific problems that ESLint does not: impure state updaters, state
// copied from props, render-time work, and accessibility. CI fails on any warning.
export default {
  blocking: "warning",
  // No score upload, share link, or crash reports leave CI. Dependency health is out of scope
  // here; the supply-chain check would also make the gate depend on a remote service.
  noScore: true,
  supplyChain: { enabled: false },
  ignore: {
    overrides: [
      {
        // The Activity table sets explicit table roles on purpose: narrow screens restyle its rows
        // with CSS display values, which drop the native table semantics in some browsers.
        files: ["src/features/activity.tsx"],
        rules: ["react-doctor/no-redundant-roles", "react-doctor/no-interactive-element-to-noninteractive-role"],
      },
      {
        // These components are already over the size and complexity bounds. ESLint's suppression
        // file (eslint-suppressions.json) counts them and fails on any new violation in these
        // files, so the debt is tracked once, there. Remove a file here when it is split.
        files: [
          "src/features/activity.tsx",
          "src/features/auth-screen.tsx",
          "src/features/overview.tsx",
          "src/features/rule-details.tsx",
          "src/features/rules.tsx",
          "src/features/settings.tsx",
        ],
        rules: ["react-doctor/no-high-complexity-react-function", "react-doctor/no-giant-component"],
      },
    ],
  },
} satisfies ReactDoctorConfig
