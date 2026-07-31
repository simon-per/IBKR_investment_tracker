/**
 * The Activity ledger, against REAL data.
 *
 * `CLAUDE.md` says to audit the transfer rows before trusting any money-added figure: an
 * incoming transfer booked as a deposit shows a portfolio-sized fake contribution, and
 * that audit used to be `manage_cash_flows list` over ssh. These assert the UI now
 * answers it — and that the badge is present, not merely the row.
 *
 * Needs: frontend dev server on BASE, backend pointed at a PRODUCTION SNAPSHOT.
 * The checked-in `portfolio.db` predates trades, cash flows and the IBKR dividend era,
 * so it exercises none of these shapes and every assertion below would fail on it.
 * Delete the snapshot afterwards — it is real account data.
 */
import { BASE, openPage, reporter } from './lib.mjs'

const { log, done } = reporter()
const { browser, page, errors } = await openPage()

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForTimeout(2000)
await page.getByRole('tab', { name: 'Activity', exact: true }).click()
await page.waitForTimeout(4000)

const panel = await page.getByRole('tabpanel').innerText()

log(/Transfer/.test(panel), 'a Transfer row is visible in the ledger')
log(/not money in/.test(panel), 'transfers are badged "not money in"')
log(/Deposit/.test(panel), 'a Deposit row is visible')

// The three defects the prod-data pass caught, each pinned so they cannot come back.
log(!/\b0\.00\b.*realized/i.test(panel), 'no BUY row asserts a 0.00 realized result')
const region = page.getByRole('region', { name: /Activity table/ })
log((await region.count()) === 1, 'the wide table is a named, keyboard-reachable scroll region')

// Fractional share counts must survive: this account trades 0.5 SOXQ, 0.3 MU, 0.1 CSU.
// A quantity column of bare "0" or "-0" is the rounding bug.
const zeroQty = (panel.match(/(^|\s)-?0(\s|$)/gm) || []).length
log(zeroQty === 0, `no quantity rounds to 0 or -0 (found ${zeroQty})`)

log(errors.length === 0, `no console errors (${errors.length}): ${errors.slice(0, 3).join(' | ')}`)

done()
await browser.close()
