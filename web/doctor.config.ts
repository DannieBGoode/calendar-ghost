import type { ReactDoctorConfig } from "react-doctor/api"

// React Doctor checks React-specific problems that ESLint does not: impure state updaters, state
// copied from props, render-time work, and accessibility. CI fails on any warning.
export default {
  blocking: "warning",
  // No score upload, share link, or crash reports leave CI. Dependency health is out of scope
  // here; the supply-chain check would also make the gate depend on a remote service.
  noScore: true,
  supplyChain: { enabled: false },
  rules: {
    // ESLint owns size and complexity for every file (complexity, max-lines-per-function), with
    // one marked exception per existing violation, so these would only report the same debt twice.
    "react-doctor/no-high-complexity-react-function": "off",
    "react-doctor/no-giant-component": "off",
  },
  ignore: {
    overrides: [
      {
        // The Activity table sets explicit table roles on purpose: narrow screens restyle its rows
        // with CSS display values, which drop the native table semantics in some browsers.
        files: ["src/features/activity.tsx"],
        rules: ["react-doctor/no-redundant-roles", "react-doctor/no-interactive-element-to-noninteractive-role"],
      },
    ],
  },
} satisfies ReactDoctorConfig
