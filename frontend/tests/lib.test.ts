import { describe, expect, it, vi } from 'vitest'

import { errorMessage } from '../src/lib/api/client'
import { reconnectDelay } from '../src/lib/backoff'
import { formatCountdown, formatMinutes, maskPhone } from '../src/lib/format'
import { applyMessage } from '../src/lib/live'
import { cleanPlateInput, formatPlate } from '../src/lib/plates'
import { windowRange } from '../src/features/resident/PassesPage'

describe('formatPlate', () => {
  it.each([
    ['UP16AB1234', 'UP16 AB 1234'],
    ['DL1CAB1234', 'DL 1C AB 1234'],
    ['DL10SAR8186', 'DL 10S AR 8186'],
    ['22BH4502EW', '22 BH 4502 EW'],
    ['HR26DK8337', 'HR26 DK 8337'],
    ['KA05M42', 'KA05 M 42'],
    ['NOTAPLATE', 'NOTAPLATE'],
  ])('%s -> %s', (plate, shown) => {
    expect(formatPlate(plate)).toBe(shown)
  })

  it('cleans what a guard types', () => {
    expect(cleanPlateInput(' up 16-ab 1234 ')).toBe('UP16AB1234')
  })
})

describe('formatting', () => {
  it('formats durations', () => {
    expect(formatMinutes(0.4)).toBe('under a minute')
    expect(formatMinutes(45)).toBe('45 min')
    expect(formatMinutes(120)).toBe('2 h')
    expect(formatMinutes(154)).toBe('2 h 34 min')
  })

  it('formats countdowns and never goes negative', () => {
    expect(formatCountdown(125_000)).toBe('2:05')
    expect(formatCountdown(400)).toBe('0:01')
    expect(formatCountdown(-5000)).toBe('0:00')
  })

  it('masks phone numbers', () => {
    expect(maskPhone('+919876543210')).toBe('+91 98•••••210')
    expect(maskPhone('+91 98•••••210')).toBe('+91 98•••••210')
    expect(maskPhone(null)).toBe('—')
  })
})

describe('reconnectDelay', () => {
  it('grows exponentially up to the cap', () => {
    const max = (attempt: number) => reconnectDelay(attempt, { random: () => 1 })
    expect(max(0)).toBe(1000)
    expect(max(1)).toBe(2000)
    expect(max(3)).toBe(8000)
    expect(max(10)).toBe(30_000)
  })

  it('never waits less than half the base (jitter floor)', () => {
    expect(reconnectDelay(5, { random: () => 0 })).toBe(500)
  })
})

describe('errorMessage', () => {
  it('uses the API detail text', () => {
    expect(errorMessage({ detail: 'Invalid email or password' }, 401)).toBe(
      'Invalid email or password',
    )
  })

  it('turns validation errors into field messages', () => {
    const body = {
      detail: [
        { loc: ['body', 'phone'], msg: 'Value error, must be a 10-digit Indian mobile number' },
      ],
    }
    expect(errorMessage(body, 422)).toBe('phone: must be a 10-digit Indian mobile number')
  })

  it('explains a network failure', () => {
    expect(errorMessage(null, 0)).toMatch(/Can’t reach the server/)
  })
})

describe('applyMessage', () => {
  it('invalidates the lists a live message affects', () => {
    const invalidateQueries = vi.fn(() => Promise.resolve())
    const client = { invalidateQueries } as unknown as Parameters<typeof applyMessage>[0]
    applyMessage(client, { type: 'approval.decided' })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ['approvals'] })
    expect(invalidateQueries).toHaveBeenCalledWith({ queryKey: ['visits'] })
    invalidateQueries.mockClear()
    applyMessage(client, { type: 'something.else' })
    expect(invalidateQueries).not.toHaveBeenCalled()
  })
})

describe('guest pass windows', () => {
  const now = new Date(2026, 10, 20, 15, 30)
  it('next 4 hours starts now', () => {
    const [from, until] = windowRange('hours', now)
    expect(from).toEqual(now)
    expect(until.getHours()).toBe(19)
  })
  it('tomorrow covers the whole next day', () => {
    const [from, until] = windowRange('tomorrow', now)
    expect([from.getDate(), from.getHours()]).toEqual([21, 0])
    expect([until.getDate(), until.getHours(), until.getMinutes()]).toEqual([21, 23, 59])
  })
})
