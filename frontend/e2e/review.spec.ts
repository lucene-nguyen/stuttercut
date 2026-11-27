// E2E flows of LEARNING-209 with the fake transcriber (tests/fixtures/review_clip.json):
// 2 sure cuts (filler "ờ", repeat "tôi") and 2 unsure (a pause, the filler "à").
import { expect, test } from '@playwright/test'

import { seriousViolations, upload, uploadAndOpen } from './helpers'

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
  const { res, added } = await upload(page, 'dài quá.mp4')
  expect(res.status()).toBe(422)
  expect(added).toEqual([]) // no job created
  await expect(page.getByRole('alert')).toHaveText(
    'dài quá.mp4 is 4:00 long. Choose a video of 3 minutes or less.',
  )
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
