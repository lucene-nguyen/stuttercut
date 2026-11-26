// E2E flows of LEARNING-209 with the fake transcriber (tests/fixtures/review_clip.json):
// 2 sure cuts (filler "ờ", repeat "tôi") and 2 unsure (a pause, the filler "à").
import { join } from 'node:path'

import AxeBuilder from '@axe-core/playwright'
import { expect, test, type Page } from '@playwright/test'

const media = (name: string) => join(process.env.E2E_TMP!, 'media', name)

async function uploadAndOpen(page: Page) {
  await page.goto('/')
  const rows = page.locator('tbody tr')
  const before = await rows.count()
  await page.setInputFiles('input[type=file]', media('bài nói thử.mp4'))
  await expect(rows).toHaveCount(before + 1)
  await expect(rows.first()).toContainText('Ready for review', { timeout: 60_000 })
  await rows
    .first()
    .getByRole('link', { name: /Review/ })
    .click()
  await expect(page.locator('.transcript')).toContainText('Xin')
}

async function seriousViolations(page: Page) {
  const result = await new AxeBuilder({ page }).analyze()
  return result.violations
    .filter((v) => v.impact === 'serious' || v.impact === 'critical')
    .map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`)
}

test('upload → review → render MP4 + XML', async ({ page }) => {
  await uploadAndOpen(page)
  await expect(page.getByTestId('cut-count')).toHaveText('0/4')
  await page.getByRole('button', { name: 'Approve all sure' }).click()
  await expect(page.getByTestId('cut-count')).toHaveText('2/4')
  await expect(page.getByTestId('saved')).not.toHaveText('−0:00.0')
  await page.getByRole('button', { name: 'Approve & render' }).click()
  await page.getByLabel(/^Both/).check()
  await page.getByRole('button', { name: /^Render .* video$/ }).click()
  const done = page.getByRole('status')
  await expect(done).toContainText('Rendered in', { timeout: 60_000 })
  await expect(done).toContainText('bài nói thử_clean.mp4 + bài nói thử_clean.xml')
  await page.getByRole('link', { name: 'Next video' }).click()
  await expect(page.locator('tbody tr').first()).toContainText('Rendered')
})

test('a 4-minute video is refused with a clear message', async ({ page }) => {
  await page.goto('/')
  const rows = page.locator('tbody tr')
  await expect(page.getByRole('heading', { name: 'Recent jobs' })).toBeVisible()
  const before = await rows.count()
  await page.setInputFiles('input[type=file]', media('dài quá.mp4'))
  await expect(page.getByRole('alert')).toHaveText(
    'dài quá.mp4 is 4:00 long. Choose a video of 3 minutes or less.',
  )
  await expect(rows).toHaveCount(before)
})

test('decisions and a missed cut survive a reload', async ({ page }) => {
  await uploadAndOpen(page)
  await page.locator('h2#tr').click() // focus off any field so the review keys apply
  await page.keyboard.press('ArrowRight') // first cut: "ờ"
  await page.keyboard.press('x')
  await page.keyboard.press('ArrowRight') // second: the repeated "tôi"
  await page.keyboard.press('k')
  const filler = page.locator('button.tok', { hasText: /^ờ$/ })
  const repeat = page.locator('button.tok', { hasText: /^tôi$/ })
  await expect(filler).toHaveClass(/\bcut\b/)
  await expect(repeat).toHaveClass(/\bkept\b/)

  // Select "rất bền" (words 14-15) and mark it as a missed filler.
  await page.evaluate(() => {
    const a = document.querySelector('[data-i="14"]')!
    const b = document.querySelector('[data-i="15"]')!
    const range = document.createRange()
    range.setStart(a.firstChild!, 0)
    range.setEnd(b.firstChild!, 2)
    window.getSelection()!.removeAllRanges()
    window.getSelection()!.addRange(range)
    document
      .querySelector('.transcript')!
      .dispatchEvent(new MouseEvent('mouseup', { bubbles: true }))
  })
  await expect(page.getByText(/^Selected:/)).toContainText('rất bền')
  await page.getByRole('button', { name: 'Mark missed cut' }).click()
  const missed = page.locator('button.tok', { hasText: 'rất bền' })
  await expect(missed).toHaveClass(/\bcut\b/)

  await page.reload()
  await expect(filler).toHaveClass(/\bcut\b/)
  await expect(repeat).toHaveClass(/\bkept\b/)
  await expect(missed).toHaveClass(/\bcut\b/)
  await expect(page.getByText('marked by you')).toBeVisible()
})

test('no serious accessibility problems on both screens', async ({ page }) => {
  await page.goto('/')
  await expect(page.locator('tbody tr').first()).toBeVisible()
  expect(await seriousViolations(page)).toEqual([])
  await page
    .locator('tbody tr')
    .first()
    .getByRole('link', { name: /Review/ })
    .click()
  await expect(page.locator('.transcript')).toContainText('Xin')
  await page.getByRole('button', { name: 'Approve & render' }).click()
  expect(await seriousViolations(page)).toEqual([])
})
