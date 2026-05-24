/** Format a unix timestamp as "il y a 2 min" / "dans 3h 12min". */
export function formatRelative(unixSec: number | null | undefined, now = Date.now()): string {
  if (unixSec === null || unixSec === undefined) return '—'
  const diffSec = Math.round(unixSec * 1000 - now) / 1000

  const future = diffSec >= 0
  const absSec = Math.abs(diffSec)

  if (absSec < 60) {
    return future ? "dans quelques secondes" : "à l'instant"
  }
  if (absSec < 3600) {
    const m = Math.round(absSec / 60)
    return future ? `dans ${m} min` : `il y a ${m} min`
  }
  if (absSec < 86_400) {
    const h = Math.floor(absSec / 3600)
    const m = Math.round((absSec - h * 3600) / 60)
    const suffix = m > 0 ? `${h}h ${m}min` : `${h}h`
    return future ? `dans ${suffix}` : `il y a ${suffix}`
  }
  const days = Math.round(absSec / 86_400)
  return future ? `dans ${days} j` : `il y a ${days} j`
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} o`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} Ko`
  return `${(bytes / (1024 * 1024)).toFixed(1)} Mo`
}

/** Format a unix timestamp as a short absolute date: "24 mai · 14:35". */
export function formatAbsolute(unixSec: number | null | undefined): string {
  if (unixSec === null || unixSec === undefined) return '—'
  const date = new Date(unixSec * 1000)
  return date.toLocaleString('fr-FR', {
    day: 'numeric',
    month: 'short',
    hour: '2-digit',
    minute: '2-digit',
  })
}
