import { RuleTester } from "eslint"
import tseslint from "typescript-eslint"
import { describe, it } from "vitest"

import { localRules } from "../../eslint.config.js"

RuleTester.describe = describe
RuleTester.it = it

new RuleTester({ languageOptions: { parser: tseslint.parser, parserOptions: { ecmaFeatures: { jsx: true } } } }).run(
  "no-literal-ui-text",
  localRules["no-literal-ui-text"],
  {
    valid: [
      "<p>{t('a.b')}</p>",
      "<p> · </p>",
      "<input aria-label={t('a.b')} />",
      "<p>{name}</p>",
      "<a href='/x' />",
      // Non-text attributes and props may hold words: identifiers, settings, and SVG paths.
      "<div className='page-card' id='rule-builder' role='status' aria-controls={open ? 'list' : undefined} />",
      "<Button variant='outline' size='sm' type='submit' />",
      "<path d='M4 14q4-6.5 8-2' fill='none' strokeLinecap='round' />",
      "<div data-tone='attention' />",
      "<AccountSelect labelId='source-account-label' />",
      // Separators and numbers carry no letters.
      "<p>{open ? '·' : '–'}</p>",
      "<p>{`${count}`}</p>",
    ],
    invalid: [
      { code: "<p>Rules</p>", errors: [{ messageId: "literal" }] },
      { code: "<input placeholder='Search' />", errors: [{ messageId: "literal" }] },
      { code: "<button aria-label={`Open ${name}`} />", errors: [{ messageId: "literal" }] },
      // Literal children inside expression containers, including conditional and logical branches.
      { code: "<p>{'Text'}</p>", errors: [{ messageId: "literal" }] },
      { code: "<span>{open ? 'Hide' : 'Show'}</span>", errors: [{ messageId: "literal" }, { messageId: "literal" }] },
      { code: "<p>{failed && 'Try again'}</p>", errors: [{ messageId: "literal" }] },
      { code: "<p>{name ?? 'Unknown'}</p>", errors: [{ messageId: "literal" }] },
      { code: "<p>{`${count} rules`}</p>", errors: [{ messageId: "literal" }] },
      // The same in UI text attributes.
      { code: "<button aria-label={open ? 'Hide' : 'Show'} />", errors: [{ messageId: "literal" }, { messageId: "literal" }] },
      { code: "<a title={stale && 'Refresh'} />", errors: [{ messageId: "literal" }] },
      // Text props of our own components.
      { code: "<DestructiveConfirmation body='Cannot be undone.' />", errors: [{ messageId: "literal" }] },
      { code: "<EndpointFields legend='Source calendar' />", errors: [{ messageId: "literal" }] },
      { code: "<Example description={`For ${name}`} />", errors: [{ messageId: "literal" }] },
      {
        code: "<Confirm confirmLabel='Remove' cancelLabel='Keep' pendingLabel='Removing…' />",
        errors: [{ messageId: "literal" }, { messageId: "literal" }, { messageId: "literal" }],
      },
      { code: "<RulePicker clearLabel='Clear' />", errors: [{ messageId: "literal" }] },
    ],
  },
)
