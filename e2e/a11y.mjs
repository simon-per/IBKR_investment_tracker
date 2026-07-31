/**
 * Keyboard and ARIA sweep: the tab strip, the four collapsible cards, sortable headers.
 *
 * Four cards put `onClick` on a `<CardHeader>` div and two tables put it on a `<th>`, so
 * those surfaces were mouse-only; `ui/tabs.tsx` had no ARIA at all. Unit tests pin the
 * shared components in isolation — this pins that the real page wires them up.
 *
 * Needs: frontend dev server on BASE. Backend optional (nothing here reads data).
 */
import { BASE, openPage, reporter } from './lib.mjs'

const { log, done } = reporter()
const { browser, page, errors } = await openPage({ width: 1440, height: 950 })

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForTimeout(2500)

log((await page.title()) === 'Portfolio Analyzer', `title is "${await page.title()}"`)

const tablist = page.getByRole('tablist')
log((await tablist.count()) === 1, 'exactly one tablist')

const tabs = page.getByRole('tab')
const tabCount = await tabs.count()
log(tabCount === 8, `8 tabs present (got ${tabCount})`)

// Roving tabIndex: the strip is one tab stop, arrows move within it.
await tabs.first().focus()
await page.keyboard.press('ArrowRight')
await page.waitForTimeout(600)
const afterRight = await page.getByRole('tab', { selected: true }).innerText()
log(afterRight === 'Activity', `ArrowRight selects Activity (got ${afterRight})`)

await page.waitForTimeout(2500)
log((await page.getByRole('tabpanel').count()) === 1, 'exactly one tabpanel is exposed')

await page.getByRole('tab', { selected: true }).focus()
await page.keyboard.press('End')
await page.waitForTimeout(600)
const afterEnd = await page.getByRole('tab', { selected: true }).innerText()
log(afterEnd === 'Tax', `End jumps to the last tab (got ${afterEnd})`)

await page.keyboard.press('Home')
await page.waitForTimeout(2500)
const afterHome = await page.getByRole('tab', { selected: true }).innerText()
log(afterHome === 'Performance', `Home returns to the first tab (got ${afterHome})`)

// The four collapsibles must be real buttons that Enter toggles.
for (const name of ['Monthly Returns', 'Monthly Deployment', 'Dividend Income', 'Performance Attribution']) {
  const btn = page.getByRole('button', { name: new RegExp(name) }).first()
  if ((await btn.count()) === 0) { log(false, `${name}: header is not a button`); continue }
  const before = await btn.getAttribute('aria-expanded')
  await btn.focus()
  await page.keyboard.press('Enter')
  await page.waitForTimeout(500)
  const after = await btn.getAttribute('aria-expanded')
  log(before === 'false' && after === 'true', `${name}: Enter toggles aria-expanded (${before} -> ${after})`)
}

const sorted = await page.locator('th[aria-sort]').count()
log(sorted > 0, `${sorted} headers carry aria-sort`)

const footer = await page.locator('footer').innerText().catch(() => '')
log(/Portfolio Analyzer v/.test(footer), 'footer reports the running build')

log(errors.length === 0, `no console errors (${errors.length}): ${errors.slice(0, 3).join(' | ')}`)

done()
await browser.close()
