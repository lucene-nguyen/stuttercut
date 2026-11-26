// E2E for the Diagnostics screen (LEARNING-229): metrics, a job trace, logs, export, axe.
import AxeBuilder from '@axe-core/playwright'
import { expect, test } from '@playwright/test'

import { upload } from './helpers'

test('diagnostics shows metrics, a trace and logs, and exports a zip', async ({ page }) => {
  const { row } = await upload(page, 'bài nói thử.mp4')
  await expect(row).toContainText('Ready for review', { timeout: 60_000 })
  const jobId = await row.getAttribute('data-job')

  await page.goto(`/#/diagnostics?job=${jobId}`)
  await expect(page.getByRole('heading', { name: /Metrics · last 7 days/ })).toBeVisible()
  await expect(page.getByTestId('metric-jobs')).not.toHaveText('0')
  const steps = page.getByRole('table', { name: /Steps of bài nói thử.mp4/ })
  await expect(steps).toContainText('transcribe')
  await expect(steps).toContainText('detect')
  await expect(page.getByRole('button', { name: /bài nói thử.mp4/ }).first()).toHaveAttribute(
    'aria-pressed',
    'true',
  )

  const logs = page.locator('table.mono tbody tr')
  await expect(logs.first()).toBeVisible()
  await page.getByRole('button', { name: /^Info \d+/ }).click()
  await expect(page.getByRole('button', { name: /^Info \d+/ })).toHaveAttribute(
    'aria-pressed',
    'true',
  )
  await expect(page.locator('table.mono tbody tr').first()).toContainText('Info')

  const download = page.waitForEvent('download')
  await page.getByRole('button', { name: 'Export diagnostics (.zip)' }).click()
  expect((await download).suggestedFilename()).toMatch(/^stuttercut-diagnostics-.*\.zip$/)
  await expect(page.getByRole('status')).toContainText('Saved stuttercut-diagnostics-')

  const result = await new AxeBuilder({ page }).analyze()
  const serious = result.violations.filter((v) => v.impact === 'serious' || v.impact === 'critical')
  expect(
    serious.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(' ')).join(', ')}`),
  ).toEqual([])
})
