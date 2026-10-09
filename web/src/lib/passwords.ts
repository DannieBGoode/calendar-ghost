/** The shortest password the server accepts. */
export const MINIMUM_PASSWORD_LENGTH = 12

/** Whether a confirmation was typed and differs from the new password. */
export function passwordMismatch(password: string, confirmation: string): boolean {
  return confirmation.length > 0 && password !== confirmation
}

/** Whether a new password is long enough and confirmed. */
export function newPasswordReady(password: string, confirmation: string): boolean {
  return password.length >= MINIMUM_PASSWORD_LENGTH && password === confirmation
}
