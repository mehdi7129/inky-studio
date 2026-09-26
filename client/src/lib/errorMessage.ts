/** Libraries may reject with a plain { message } object instead of an Error. */
export function errorMessage(error: unknown, fallback: string): string {
  const message = typeof error === 'string'
    ? error
    : error !== null && typeof error === 'object' && 'message' in error
      ? error.message
      : undefined
  return typeof message === 'string' && message.trim() ? message.trim() : fallback
}
