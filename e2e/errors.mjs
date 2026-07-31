/**
 * With the backend STOPPED, no surface may fall back to an empty-data message.
 *
 * This is the highest-value check in the directory. "No portfolio data — sync to get
 * started" shown during an outage tells the user their account is empty, and six
 * components had that exact bug. A failure must look like a failure.
 *
 * Needs: frontend dev server on BASE, backend DELIBERATELY DOWN.
 *
 * The waits are long because TanStack retries once before surfacing an error; shorter
 * ones produced false failures that read exactly like real defects.
 */
import { BASE, openPage, reporter } from './lib.mjs'

const { log, done } = reporter()
const { browser, page } = await openPage({ width: 1500, height: 1100 })

await page.goto(BASE, { waitUntil: 'domcontentloaded' })
await page.waitForTimeout(12000)

const perf = await page.getByRole('tabpanel').innerText()
log(/didn't respond/.test(perf), 'Performance shows an explicit backend-error message')
log(!/No portfolio data yet/.test(perf), 'does NOT show the "sync to get started" empty state')

for (const name of ['Monthly Returns', 'Monthly Deployment', 'Dividend Income', 'Performance Attribution']) {
  const btn = page.getByRole('button', { name: new RegExp(name) }).first()
  if ((await btn.count()) === 0) { log(false, `${name}: header missing`); continue }
  await btn.click()
  await page.waitForTimeout(600)
}

const opened = await page.getByRole('tabpanel').innerText()
const hits = (opened.match(/didn't respond/g) || []).length
log(hits >= 4, `${hits} panels report the backend failure explicitly`)
log(!/Not enough data to compute/.test(opened), 'Monthly Returns does not claim "not enough data"')
log(!/No contribution history yet/.test(opened), 'Monthly Deployment does not claim "no history"')
log(!/No dividend data available/.test(opened), 'Dividend Income does not claim "no dividends"')
log(/Avg Monthly unavailable/.test(opened), 'the contributions strip says unavailable instead of vanishing')

await page.getByRole('tab', { name: 'Activity' }).click()
await page.waitForTimeout(9000)
const act = await page.getByRole('tabpanel').innerText()
log(/didn't respond/.test(act), 'Activity reports the failure')
log(!/No activity in this window/.test(act), 'Activity does not claim "no activity"')

await page.getByRole('tab', { name: 'Fundamentals' }).click()
await page.waitForTimeout(9000)
const fund = await page.getByRole('tabpanel').innerText()
log(/didn't respond/.test(fund), 'Fundamentals reports the failure')
log(!/Click "Sync Now"/.test(fund), 'Fundamentals does not tell the user to run a sync that cannot work')

done()
await browser.close()
