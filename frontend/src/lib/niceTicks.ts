/**
 * Round axis bounds out to a "nice" step, aiming at roughly `targetCount` ticks.
 *
 * Extracted from two charts that each solved this differently. `ForecastTab` targeted a
 * tick *count* and derived the step from it; `PortfolioValueChart` used a fixed
 * 200/1000/2500/10000 ladder chosen from the data range alone — with no idea how tall
 * the chart was. That ladder is why a 20k range put eight labels into a 280px-tall
 * phone chart, roughly 35px apart.
 *
 * Targeting a count is the version that survives, because the count is the thing that
 * depends on the viewport. Unlike the ForecastTab original this handles a negative
 * minimum: the portfolio chart's profit/loss series goes below zero.
 */
export interface Axis {
  domain: [number, number]
  ticks: number[]
}

/**
 * 1, 2, 2.5, 5, 10 × a power of ten — the steps that read as round numbers on an axis.
 *
 * 2.5 is in the ladder because without it the rungs are too far apart to track a target
 * count: a 20k range asked for 8 ticks and one asked for 4 both landed on a step of
 * 5000, i.e. the target was ignored. 2500 and 25000 are round for money, and the
 * PortfolioValueChart ladder this replaces had 2500 in it for exactly that reason.
 */
function niceStep(raw: number): number {
  if (!isFinite(raw) || raw <= 0) return 1
  const magnitude = Math.pow(10, Math.floor(Math.log10(raw)))
  const normalised = raw / magnitude
  const step =
    normalised <= 1 ? 1
    : normalised <= 2 ? 2
    : normalised <= 2.5 ? 2.5
    : normalised <= 5 ? 5
    : 10
  return step * magnitude
}

export function niceTicks(min: number, max: number, targetCount: number): Axis {
  if (!isFinite(min) || !isFinite(max) || targetCount < 1) {
    return { domain: [0, 1], ticks: [0, 1] }
  }

  // A flat series still needs an axis with height, or every tick lands on one line.
  if (max === min) {
    const step = niceStep(Math.abs(max) / targetCount || 1)
    return { domain: [min - step, max + step], ticks: [min - step, min, max + step] }
  }

  const step = niceStep((max - min) / targetCount)
  const lo = Math.floor(min / step) * step
  const hi = Math.ceil(max / step) * step

  const ticks: number[] = []
  // Accumulate by index rather than `i += step`: repeated addition of a fractional step
  // drifts, and the drift shows up as an axis label reading 2999.9999999999995.
  const count = Math.round((hi - lo) / step)
  for (let i = 0; i <= count; i++) ticks.push(lo + i * step)

  return { domain: [lo, hi], ticks }
}
