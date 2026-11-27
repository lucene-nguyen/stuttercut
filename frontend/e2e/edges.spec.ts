// E2E for the LEARNING-209 follow-up: cut edge editing and the Web Audio clean preview.
// The fake transcriber's first cut is the filler "ờ" at 1.00–1.30 s. Audio itself is not checked.
import { expect, test } from '@playwright/test'

import { seriousViolations, uploadAndOpen } from './helpers'

test('nudge cut edges, see the times, and the plan is fetched again', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  await uploadAndOpen(page)

  await page.locator('h2#tr').click()
  await page.keyboard.press('ArrowRight') // select the first cut
  const editor = page.getByRole('region', { name: 'Cut edges' })
  await expect(editor).toBeVisible()
  await expect(page.getByTestId('edge-start')).toHaveText('00:01.00')
  await expect(page.getByTestId('edge-end')).toHaveText('00:01.30')

  const patch = page.waitForRequest((r) => r.method() === 'PATCH' && r.url().includes('/cuts/'))
  const plan = page.waitForRequest((r) => r.method() === 'GET' && r.url().endsWith('/plan'))
  await page.getByRole('button', { name: 'Start 10 ms earlier' }).click()
  expect((await patch).postDataJSON()).toEqual({ start_s: 0.99, end_s: 1.3 })
  await plan
  await expect(page.getByTestId('edge-start')).toHaveText('00:00.99')
  // effective = where the 25 fps render really cuts: the edited start (no padding) 0.99 → nearest
  // frame 1.00; the unedited end has 100 ms of silence before 'hôm' (1.40), so its padding goes
  // outward into it: 1.30 + 40 ms = 1.34 → nearest frame 1.36
  await expect(page.getByTestId('edge-start-eff')).toHaveText('00:01.00')
  await expect(page.getByTestId('edge-end-eff')).toHaveText('00:01.36')

  const planAgain = page.waitForRequest((r) => r.method() === 'GET' && r.url().endsWith('/plan'))
  await page.keyboard.press('Shift+ArrowRight') // end edge +10 ms
  await planAgain
  await expect(page.getByTestId('edge-end')).toHaveText('00:01.31')
  await expect(page.getByTestId('edge-end-eff')).toHaveText('00:01.32') // edited 1.31 → nearest frame 1.32
  await expect(editor).toContainText('edited')
  await expect(page.locator('button.tok', { hasText: /^ờ$/ })).toHaveClass(/\bcut\b/) // approved

  await page.reload()
  await page.locator('h2#tr').click()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByTestId('edge-start')).toHaveText('00:00.99')
  await expect(page.getByTestId('edge-end')).toHaveText('00:01.31')
  await page.getByRole('button', { name: 'Reset edges' }).click()
  await expect(page.getByTestId('edge-start')).toHaveText('00:01.00')
  expect(await seriousViolations(page)).toEqual([])
  expect(errors).toEqual([])
})

test('clean mode plays and pauses without errors, and can be switched off', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (e) => errors.push(e.message))
  page.on('console', (m) => m.type() === 'error' && errors.push(m.text()))
  await uploadAndOpen(page)
  await page.getByRole('button', { name: 'Approve all sure' }).click()

  const audio = page.waitForResponse((r) => r.url().endsWith('/preview-audio'))
  await page.getByRole('button', { name: 'Play clean preview' }).click()
  expect((await audio).status()).toBe(200)
  await expect(page.getByRole('button', { name: 'Pause clean preview' })).toBeVisible()
  await expect(page.getByTestId('clean-clock')).toContainText('/ 0:09.4') // 10 s minus the two sure cuts (0.96–1.36, 2.08–2.28)
  await page.getByRole('button', { name: 'Pause clean preview' }).click()
  await expect(page.getByRole('button', { name: 'Play clean preview' })).toBeVisible()

  await page.getByLabel(/Play the clean version/).uncheck()
  await expect(page.locator('video')).toHaveAttribute('controls', '')
  await expect(page.getByRole('button', { name: /clean preview/ })).toHaveCount(0)
  expect(await seriousViolations(page)).toEqual([])
  expect(errors).toEqual([])
})

test('five fast nudges save the last value', async ({ page }) => {
  await uploadAndOpen(page)
  await page.locator('h2#tr').click()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByTestId('edge-start')).toHaveText('00:01.00')
  const last = page.waitForResponse(
    (r) => r.request().method() === 'PATCH' && r.request().postDataJSON()?.start_s === 0.95,
  )
  for (let i = 0; i < 5; i++) await page.keyboard.press('Alt+ArrowLeft')
  await expect(page.getByTestId('edge-start')).toHaveText('00:00.95')
  expect((await last).status()).toBe(200) // the latest edges were saved
  await page.reload()
  await page.locator('h2#tr').click()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByTestId('edge-start')).toHaveText('00:00.95')
})
