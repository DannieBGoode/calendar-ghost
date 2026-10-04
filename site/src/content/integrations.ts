/** The self-hosting guide's check for a token, word for word (section 6). */
export const STATUS_CHECK_COMMAND =
  'curl -H "Authorization: Bearer $CALENDAR_GHOST_TOKEN" https://ghost.example.lan/api/v1/status'
