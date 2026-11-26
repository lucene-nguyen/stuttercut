import { join } from 'node:path'

import type { Page } from '@playwright/test'

export const media = (name: string) => join(process.env.E2E_TMP!, 'media', name)

const jobIds = async (page: Page) =>
  ((await (await page.request.get('/api/jobs')).json()) as { id: string }[]).map((j) => j.id)

/** Upload through the drop zone; returns the upload response and the new job's row.
 * The new job is found by diffing the job list (Chrome drops the body of a big upload's reply). */
export async function upload(page: Page, name: string) {
  await page.goto('/')
  const before = new Set(await jobIds(page))
  const [res] = await Promise.all([
    page.waitForResponse((r) => r.url().includes('/api/jobs?name=')),
    page.setInputFiles('input[type=file]', media(name)),
  ])
  const added = (await jobIds(page)).filter((id) => !before.has(id))
  return { res, added, row: page.locator(`tr[data-job="${added[0]}"]`) }
}
