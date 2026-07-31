/**
 * Visit all eight tabs and assert each renders without console errors.
 *
 * The cheapest check that catches a whole class of breakage — a `Decimal + None` on a
 * response shape, a lazy chunk that never resolves, a crash inside one panel. Every
 * other backend test calls services directly, which is how a serialization bug reached
 * production behind a green suite.
 *
 * Needs: frontend dev server on BASE, backend up with data.
 */
import { BASE, TABS, openPage, reporter } from './lib.mjs'

const { log, done } = reporter()
const { browser, page, errors } = await openPage()

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForTimeout(2000)

for (const tab of TABS) {
  const before = errors.length
  await page.getByRole('tab', { name: tab, exact: true }).click()
  await page.waitForTimeout(3500)

  const panel = await page.getByRole('tabpanel').innerText()
  const empty = panel.trim().length < 40
  const boundary = /Something went wrong/i.test(panel)
  // The lazy panels have their own boundary; a stuck fallback means the chunk never came.
  const stuck = new RegExp(`Loading ${tab}`).test(panel)
  const chunkFailed = new RegExp(`${tab} couldn't load`).test(panel)

  log(
    !empty && !boundary && !stuck && !chunkFailed,
    `${tab}: renders (${panel.trim().length} chars)` +
      (boundary ? ' — ERROR BOUNDARY' : '') +
      (stuck ? ' — SUSPENSE STUCK' : '') +
      (chunkFailed ? ' — CHUNK FAILED' : '')
  )
  log(
    errors.length === before,
    `${tab}: no new console errors${errors.length > before ? ': ' + errors.slice(before, before + 1) : ''}`
  )
}

done()
await browser.close()
