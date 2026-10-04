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

// Attributes and props whose values are identifiers, addresses, or settings, never words a person
// reads. Every other attribute, including text props of our own components such as `body`,
// `legend`, `description`, or `confirmLabel`, may not hold literal text. `data-*` is non-text too.
const NON_TEXT_ATTRIBUTES = new Set([
  "className",
  "id",
  "key",
  "href",
  "src",
  "type",
  "variant",
  "size",
  "role",
  "name",
  "value",
  "rel",
  "target",
  "method",
  "autoComplete",
  "inputMode",
  "htmlFor",
  "dateTime",
  "aria-hidden",
  "aria-controls",
  "aria-describedby",
  "aria-labelledby",
  "aria-activedescendant",
  "aria-current",
  "aria-expanded",
  "aria-haspopup",
  "aria-invalid",
  "aria-live",
  "aria-busy",
  "aria-selected",
  "aria-orientation",
  "scope",
  "referrerPolicy",
  "decoding",
  // SVG geometry and paint.
  "d",
  "fill",
  "stroke",
  "strokeLinecap",
  "strokeLinejoin",
  // Our components' element ids and modes.
  "labelId",
  "errorId",
  "idPrefix",
  "describedBy",
  "mode",
  "kind",
  "state",
])
const hasLetters = (text) => /\p{L}/u.test(text)

/** The literal strings an expression can produce, through conditional and logical branches. */
function literalTexts(node) {
  if (!node) return []
  if (node.type === "Literal") return typeof node.value === "string" && hasLetters(node.value) ? [node] : []
  if (node.type === "TemplateLiteral") return node.quasis.some((quasi) => hasLetters(quasi.value.cooked ?? "")) ? [node] : []
  if (node.type === "ConditionalExpression") return [...literalTexts(node.consequent), ...literalTexts(node.alternate)]
  if (node.type === "LogicalExpression") return [...literalTexts(node.left), ...literalTexts(node.right)]
  return []
}

/** Reports English written straight into JSX; copy belongs in web/src/i18n/locales (ADR 0026). */
const noLiteralUiText = {
  meta: {
    type: "problem",
    schema: [],
    messages: { literal: "Move this text into a catalog under web/src/i18n/locales/en and render it with t()." },
  },
  create(context) {
    const report = (nodes) => {
      for (const node of nodes) context.report({ node, messageId: "literal" })
    }
    return {
      JSXText(node) {
        if (hasLetters(node.value)) context.report({ node, messageId: "literal" })
      },
      JSXExpressionContainer(node) {
        // Children only; attribute values are checked with their attribute's name below.
        if (node.parent.type === "JSXElement" || node.parent.type === "JSXFragment") report(literalTexts(node.expression))
      },
      JSXAttribute(node) {
        if (node.name.type !== "JSXIdentifier") return
        const name = node.name.name
        if (NON_TEXT_ATTRIBUTES.has(name) || name.startsWith("data-")) return
        report(literalTexts(node.value?.type === "JSXExpressionContainer" ? node.value.expression : node.value))
      },
    }
  },
}

export const localRules = { "no-literal-ui-text": noLiteralUiText }

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
  {
    files: ["src/**/*.tsx"],
    ignores: ["src/**/*.test.tsx", "src/i18n/**"],
    plugins: { "calendar-ghost": { rules: localRules } },
    rules: { "calendar-ghost/no-literal-ui-text": "error" },
  },
)
