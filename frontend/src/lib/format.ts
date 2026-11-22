/** Dates, times and durations, in Indian English (or Hindi) and Indian time. */

export const TIME_ZONE = 'Asia/Kolkata'

function locale(lang: string): string {
  return lang === 'hi' ? 'hi-IN' : 'en-IN'
}

export function formatTime(iso: string, lang = 'en'): string {
  return new Intl.DateTimeFormat(locale(lang), {
    hour: 'numeric',
    minute: '2-digit',
    timeZone: TIME_ZONE,
  }).format(new Date(iso))
}

export function formatDateTime(iso: string, lang = 'en'): string {
  return new Intl.DateTimeFormat(locale(lang), {
    day: 'numeric',
    month: 'short',
    hour: 'numeric',
    minute: '2-digit',
    timeZone: TIME_ZONE,
  }).format(new Date(iso))
}

export function formatDay(isoDate: string, lang = 'en'): string {
  // A plain date ("2026-11-20") is already an Indian calendar day: format it as UTC.
  return new Intl.DateTimeFormat(locale(lang), {
    day: 'numeric',
    month: 'short',
    timeZone: 'UTC',
  }).format(new Date(`${isoDate}T00:00:00Z`))
}

/** "1 h 20 min", "45 min", "under a minute". */
export function formatMinutes(minutes: number): string {
  if (minutes < 1) return 'under a minute'
  const rounded = Math.round(minutes)
  const h = Math.floor(rounded / 60)
  const m = rounded % 60
  if (h === 0) return `${m.toString()} min`
  return m === 0 ? `${h.toString()} h` : `${h.toString()} h ${m.toString()} min`
}

/** "2:05" for a countdown; never negative. */
export function formatCountdown(ms: number): string {
  const total = Math.max(0, Math.ceil(ms / 1000))
  const minutes = Math.floor(total / 60)
  const seconds = total % 60
  return `${minutes.toString()}:${seconds.toString().padStart(2, '0')}`
}

/** "just now", "4 min ago", "2 h ago", then the date. */
export function formatAgo(iso: string, now: number = Date.now()): string {
  const minutes = Math.floor((now - new Date(iso).getTime()) / 60_000)
  if (minutes < 1) return 'just now'
  if (minutes < 60) return `${minutes.toString()} min ago`
  const hours = Math.floor(minutes / 60)
  if (hours < 24) return `${hours.toString()} h ago`
  return formatDateTime(iso)
}

export function titleCase(value: string): string {
  const text = value.replaceAll('_', ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}
