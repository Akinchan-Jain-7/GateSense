/**
 * Reconnect delay for the live connection: exponential (1 s, 2 s, 4 s, ...) up to a cap,
 * with "full jitter" so a hundred guard consoles that lost Wi-Fi together don't all
 * reconnect in the same millisecond.
 */
export function reconnectDelay(
  attempt: number,
  {
    base = 1000,
    max = 30_000,
    random = Math.random,
  }: { base?: number; max?: number; random?: () => number } = {},
): number {
  const ceiling = Math.min(max, base * 2 ** Math.max(0, attempt))
  return Math.round(base / 2 + random() * (ceiling - base / 2))
}
