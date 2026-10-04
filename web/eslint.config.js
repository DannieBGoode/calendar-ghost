import js from "@eslint/js"
import globals from "globals"
import reactHooks from "eslint-plugin-react-hooks"
import reactRefresh from "eslint-plugin-react-refresh"
import tseslint from "typescript-eslint"

// Folders depend inward, like the backend's layers: features compose components, components
// render lib, and lib (API access, view models, and hooks) imports neither. Each regex matches an
// alias import (`@/features/x`) and a relative one (`../features/x`).
const featureImports = {
  regex: "^(?:@/|(?:\\.\\./)+)features/",
  message: "Only features may import features.",
}
const componentImports = {
  regex: "^(?:@/|(?:\\.\\./)+)components/",
  message: "lib must not import components.",
}
const appComponentImports = {
  // From components/ui, `../x` is an app component; `./x` is another primitive.
  regex: "^(?:(?:@/|(?:\\.\\./)+)components/(?!ui/)|\\.\\./(?!\\.\\./))",
  message: "Shared UI primitives in components/ui must not depend on app components.",
}

export default tseslint.config(
  { ignores: ["dist", "../src/calendar_sync/interfaces/api/static", "src/lib/api-schema.ts"] },
  {
    extends: [
      js.configs.recommended,
      ...tseslint.configs.strictTypeChecked,
      ...tseslint.configs.stylisticTypeChecked,
    ],
    files: ["**/*.{ts,tsx}"],
    languageOptions: {
      ecmaVersion: 2022,
      globals: globals.browser,
      parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
    },
    linterOptions: { reportUnusedDisableDirectives: "error" },
    plugins: { "react-hooks": reactHooks, "react-refresh": reactRefresh },
    rules: {
      ...reactHooks.configs.recommended.rules,
      "react-refresh/only-export-components": ["warn", { allowConstantExport: true }],
      // The codebase writes object shapes as type aliases.
      "@typescript-eslint/consistent-type-definitions": ["error", "type"],
      // `onClick={() => setOpen(false)}` is the React idiom, not a misused void value.
      "@typescript-eslint/no-confusing-void-expression": ["error", { ignoreArrowShorthand: true }],
      "@typescript-eslint/restrict-template-expressions": ["error", { allowNumber: true }],
      // `||` deliberately treats an empty name or a false flag as missing.
      "@typescript-eslint/prefer-nullish-coalescing": ["error", { ignorePrimitives: { string: true, boolean: true } }],
      // Size and complexity bounds, as Ruff's C90 and PLR rules set for the backend. No code is
      // exempt: split a function or file that reaches a bound instead of disabling the rule.
      complexity: ["error", 10],
      "max-depth": ["error", 4],
      "max-params": ["error", 4],
      "max-lines-per-function": ["error", { max: 150, skipBlankLines: true, skipComments: true }],
      "max-lines": ["error", { max: 500, skipBlankLines: true, skipComments: true }],
    },
  },
  {
    files: ["src/lib/**/*.{ts,tsx}"],
    ignores: ["**/*.test.{ts,tsx}"],
    rules: { "no-restricted-imports": ["error", { patterns: [featureImports, componentImports] }] },
  },
  {
    files: ["src/components/**/*.{ts,tsx}"],
    ignores: ["src/components/ui/**", "**/*.test.{ts,tsx}"],
    rules: { "no-restricted-imports": ["error", { patterns: [featureImports] }] },
  },
  {
    files: ["src/components/ui/**/*.{ts,tsx}"],
    rules: { "no-restricted-imports": ["error", { patterns: [featureImports, appComponentImports] }] },
  },
  {
    // Tests read whole scenarios top to bottom; size limits would only split them arbitrarily.
    // A missing element fails the test either way, so a non-null assertion hides nothing there.
    files: ["**/*.test.{ts,tsx}"],
    rules: {
      "max-lines": "off",
      "max-lines-per-function": "off",
      "@typescript-eslint/no-non-null-assertion": "off",
    },
  },
)
