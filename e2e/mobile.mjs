/**
 * The phone check: 390x844, every tab.
 *
 * Chunk boundaries were the last thing no unit test could see; this is the second.
 * Horizontal overflow is a property of the assembled page at a real width — jsdom
 * loads no CSS, so nothing in `frontend/src/**` can observe it, and every other script
 * in this directory opens at 1440px or wider.
 *
 * Two assertions here are deliberately paired, and the pairing is the point:
 *
 *   (1) the document never scrolls sideways, and
 *   (6) the tab strip stays stuck to the top.
 *
 * The lazy way to make (1) pass is `body { overflow-x: hidden }`, which does not
 * remove an overflow but clips it — and which forces the block axis to
 * `overflow-y: auto`, killing `position: sticky`. So that shortcut passes (1) and
 * fails (6). Do not "fix" one without reading the other.
 *
 * Assertion (2) is what makes a failure actionable: it names the offending element and
 * its width, so "the page scrolls" becomes "div.flex.items-center.gap-2 is 512px in a
 * 324px box".
 *
 * PRECONDITION: dev server on BASE *and a backend with data*. With an empty database
 * every panel is an empty state, and an empty state cannot overflow — so a data-less
 * run passes vacuously, exactly like `a11y` does. Point DATABASE_URL at a populated
 * copy first.
 *
 * SCREENSHOT=1 writes mobile-<tab>.png next to this file (already gitignored — the
 * screenshots contain real account data and this repo is public).
 */
import { BASE, PHONE, TABS, openPage, reporter } from './lib.mjs'

const { log, done } = reporter()
const { browser, page, errors } = await openPage(PHONE)

/**
 * Elements sticking out past the viewport, ignoring the ones that do so by design.
 *
 * Skipped: anything `position: fixed` (portaled popovers are collision-aware and never
 * contribute to document scrollWidth) and anything inside a deliberate horizontal
 * scroller, whose overflow is clipped by its own container rather than the page.
 */
const findOverflowing = () =>
  page.evaluate(() => {
    const out = []
    const limit = document.documentElement.clientWidth
    for (const el of document.querySelectorAll('body *')) {
      const style = getComputedStyle(el)
      if (style.position === 'fixed' || style.display === 'none') continue

      let inScroller = false
      for (let p = el.parentElement; p && p !== document.body; p = p.parentElement) {
        const ox = getComputedStyle(p).overflowX
        if (ox === 'auto' || ox === 'scroll') { inScroller = true; break }
      }
      if (inScroller) continue

      const r = el.getBoundingClientRect()
      if (r.width === 0 && r.height === 0) continue
      if (r.right > limit + 1 || r.left < -1) {
        const cls = (el.getAttribute('class') || '').trim().split(/\s+/).slice(0, 3).join('.')
        out.push(
          `${el.tagName.toLowerCase()}${el.id ? '#' + el.id : ''}${cls ? '.' + cls : ''} ` +
          `[${Math.round(r.left)}..${Math.round(r.right)}] w=${Math.round(r.width)}`,
        )
      }
    }
    return out.slice(0, 4)
  })

const horizontalOverflow = () =>
  page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )

/** Back to the top of the document, so a click target is not below a long panel. */
const toTop = async () => {
  await page.evaluate(() => window.scrollTo(0, 0))
  await page.waitForTimeout(200)
}

/**
 * Select a tab, and report whether a real tap could reach it.
 *
 * The distinction matters: while the page overflows horizontally, Playwright's
 * actionability check refuses the click outright ("element is outside of the
 * viewport") — which is a genuine finding, but aborting on it would throw away the
 * eight tabs' worth of measurements this script exists to collect. So a refused tap is
 * logged as a failure and the run continues through a scripted DOM click.
 */
const selectTab = async (name) => {
  const tab = page.getByRole('tab', { name })
  await tab.evaluate(el => el.scrollIntoView({ inline: 'nearest', block: 'nearest' }))
  try {
    await tab.click({ timeout: 4000 })
    return true
  } catch {
    await tab.evaluate(el => el.click())
    return false
  }
}

try {

await page.goto(BASE, { waitUntil: 'networkidle' })
await page.waitForTimeout(1500)

for (const tab of TABS) {
  await toTop()
  const before = errors.length
  const tappable = await selectTab(tab)
  await page.waitForTimeout(1200)

  log(tappable, `${tab}: the tab itself is reachable by tap`)

  // 1 — the headline assertion. A pixel of slack for fractional layout widths, the
  // same slack ScrollableTable already documents for its edge fades.
  const overflow = await horizontalOverflow()
  log(overflow <= 1, `${tab}: no horizontal page scroll (${overflow}px)`)

  // 2 — and which element, when there is one.
  const offenders = await findOverflowing()
  log(offenders.length === 0, `${tab}: nothing laid out past the viewport${offenders.length ? ' — ' + offenders.join(' | ') : ''}`)

  // 7 — charts fit the box they sit in. Measured against the nearest ancestor that
  // actually has a width: recharts' own ResponsiveContainer div reports clientWidth 0,
  // so comparing to the immediate parent silently passed or failed at random.
  const wideCharts = await page.evaluate(() =>
    [...document.querySelectorAll('.recharts-wrapper')].filter(w => {
      let box = w.parentElement
      while (box && box.clientWidth === 0) box = box.parentElement
      const limit = box ? box.clientWidth : document.documentElement.clientWidth
      return w.getBoundingClientRect().width > limit + 1
    }).length)
  log(wideCharts === 0, `${tab}: ${wideCharts} chart(s) wider than their container`)

  // 4 — no new console errors from the mobile rendering.
  log(errors.length === before, `${tab}: no console errors (${errors.length - before})`)

  if (process.env.SCREENSHOT) {
    await page.screenshot({ path: `mobile-${tab.toLowerCase()}.png`, fullPage: true })
  }
}

// 5 — every tab is actually reachable in the scrolling strip, and reaching the last
// one did not leave the page scrolled sideways.
const reached = await page.evaluate(() => document.querySelectorAll('[role="tab"]').length)
log(reached === TABS.length, `all ${TABS.length} tabs present in the strip (${reached})`)
log((await horizontalOverflow()) <= 1, 'no horizontal scroll after visiting every tab')

// 3 — tap targets. The hard floor is WCAG 2.2 AA's 24x24; 44px is asserted only for
// the two control sets deliberately sized for it. A flat 44 everywhere would fail the
// theme toggle and every size="sm" button on day one, and a suite of phantom failures
// teaches people to ignore it.
await toTop()
await selectTab('Performance')
await page.waitForTimeout(800)

const targets = await page.evaluate(() => {
  const visible = el => {
    const r = el.getBoundingClientRect()
    return r.width > 0 && r.height > 0 && getComputedStyle(el).visibility !== 'hidden'
  }
  const tiny = []
  for (const el of document.querySelectorAll('button, [role="tab"], a[href], select, input')) {
    if (!visible(el)) continue
    const r = el.getBoundingClientRect()
    if (r.width < 24 || r.height < 24) {
      tiny.push(`${el.tagName.toLowerCase()}"${(el.textContent || el.getAttribute('aria-label') || '').trim().slice(0, 20)}" ${Math.round(r.width)}x${Math.round(r.height)}`)
    }
  }
  const tabs = [...document.querySelectorAll('[role="tab"]')]
    .filter(t => t.getBoundingClientRect().height < 44).length
  return { tiny: tiny.slice(0, 5), shortTabs: tabs }
})
log(targets.tiny.length === 0, `no tap target under 24px${targets.tiny.length ? ' — ' + targets.tiny.join(' | ') : ''}`)
log(targets.shortTabs === 0, `every tab trigger is at least 44px tall (${targets.shortTabs} short)`)

// 6 — the strip survives a scroll. Read this together with (1); see the docblock.
await page.evaluate(() => window.scrollTo(0, 600))
await page.waitForTimeout(300)
const stripTop = await page.evaluate(() => {
  const el = document.querySelector('[role="tablist"]')
  return el ? Math.round(el.getBoundingClientRect().top) : null
})
// `Math.abs`, not `<= 1`: a strip that is not sticky at all scrolls off the top and
// reports a large NEGATIVE offset, which a one-sided bound accepts. Pinned means it sat
// still, so the distance from 0 is what is being asserted.
log(
  stripTop !== null && Math.abs(stripTop) <= 1,
  `tab strip stays pinned while the page scrolls (top=${stripTop})`,
)

} catch (e) {
  // Report what did run: a timeout partway through is itself a finding, and losing
  // eight tabs' worth of results to it wastes the run.
  log(false, `run aborted: ${e.message.split('\n')[0]}`)
} finally {
  done()
  await browser.close()
}
