import { expect, test } from '@playwright/test'

import { adminGet, cameraKey, fixture, pageAs, sendRead } from './helpers.js'

const unique = () => Math.random().toString(36).slice(2, 7).toUpperCase()

/** The plate chip's accessible name groups characters with spaces: match either way. */
const plateName = (plate: string) => new RegExp(`^Plate ${plate.split('').join('\\s?')}$`)

test('a resident’s car is let in and appears on the guard console', async ({
  browser,
  request,
}) => {
  const guard = await pageAs(browser, request, 'guard', '/guard')
  await expect(guard.getByRole('heading', { name: 'Gate console' })).toBeVisible()
  await expect(guard.getByText('Live', { exact: true })).toBeVisible()

  const vehicles = await adminGet<{ items: { plate_normalized: string }[] }>(
    request,
    '/api/v1/vehicles?limit=50&vehicle_type=car',
  )
  const plate = vehicles.items[7]?.plate_normalized ?? ''
  const key = await cameraKey(request, 'Service Gate - entry camera')

  const read = await sendRead(request, key, plate)
  expect(read.event.match_result).toBe('resident')

  // Pushed over the WebSocket: no reload.
  const arrivals = guard.getByRole('region', { name: 'Arrivals' })
  const row = arrivals
    .getByRole('article')
    .filter({ has: guard.getByRole('img', { name: plateName(plate) }) })
    .first()
  await expect(row).toBeVisible()
  await expect(row.getByText('Resident')).toBeVisible()
  await expect(row.getByText('In', { exact: true })).toBeVisible()
})

test('an unknown visitor is registered by the guard and approved by the resident', async ({
  browser,
  request,
}) => {
  const name = `Kabir Test ${unique()}`
  const guard = await pageAs(browser, request, 'guard', '/guard')
  const resident = await pageAs(browser, request, 'resident', '/resident')
  await expect(resident.getByRole('heading', { name: 'Approvals' })).toBeVisible()

  await guard.getByRole('button', { name: 'Register visitor' }).first().click()
  const form = guard.getByRole('dialog', { name: 'Register a visitor' })
  await form.getByText('Guest', { exact: true }).click()
  await form.getByLabel('Visitor name').fill(name)
  // A fresh number: the API recognises returning visitors by phone (and updates the name).
  await form
    .getByLabel('Mobile number')
    .fill(`9${String(Math.floor(Math.random() * 1e9)).padStart(9, '0')}`)
  await form.getByLabel('Flat').selectOption({ label: 'B-402' })
  await form.getByLabel('Vehicle number (optional)').fill('DL 8C AF 4521')
  await form.getByRole('button', { name: 'Ask the resident' }).click()
  await expect(guard.getByText(`Asked B-402 to approve ${name}`)).toBeVisible()

  // The resident's phone gets the request live, with a countdown.
  const card = resident.locator('main section').filter({ hasText: name })
  await expect(card).toBeVisible()
  await card.getByRole('button', { name: 'Approve' }).click()
  await expect(resident.getByText(`${name} can come in`)).toBeVisible()

  // The guard sees the decision without refreshing.
  const waiting = guard.getByRole('region', { name: 'Waiting for a decision' })
  const approved = waiting.getByRole('article').filter({ hasText: name })
  await expect(approved.getByText('Approved, on the way in')).toBeVisible()
  await approved.getByRole('button', { name: 'Mark entered' }).click()
  await expect(guard.getByRole('region', { name: 'Inside now' }).getByText(name)).toBeVisible()
})

test('an overstaying visitor reaches the guard as a call task and is resolved', async ({
  browser,
  request,
}) => {
  const name = `Overstay Test ${unique()}`
  const guard = await pageAs(browser, request, 'guard', '/guard')
  await expect(guard.getByText('Live', { exact: true })).toBeVisible()

  fixture('overstay', name) // a visit 2 h in on a 10-minute limit; the real ladder runs

  const alerts = guard.getByRole('region', { name: 'Alerts and calls' })
  const task = alerts.getByRole('article').filter({ hasText: name })
  await expect(task.getByText('Call the resident of B-402')).toBeVisible()
  await expect(task.getByRole('link', { name: /Priya Sharma/ })).toHaveAttribute(
    'href',
    /^tel:\+91/,
  )

  await task.getByRole('button', { name: 'Spoke to them' }).click()
  await expect(guard.getByText('Marked as spoken to')).toBeVisible()
  await expect(task).toHaveCount(0)
})
