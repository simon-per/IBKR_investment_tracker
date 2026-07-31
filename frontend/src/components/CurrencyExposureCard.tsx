import { useMemo, useState } from 'react'
import { Card, CardContent } from '@/components/ui/card'
import { CollapsibleCardHeader } from '@/components/ui/CollapsibleCardHeader'
import { ScrollableTable } from '@/components/ui/ScrollableTable'
import { useBaseCurrency, useCurrencySymbol } from '@/lib/CurrencyContext'
import {
  computeCurrencyExposure,
  foreignQuotedPct,
  type CurrencyExposureInput,
} from '@/lib/currencyExposure'

interface CurrencyExposureCardProps {
  positions: CurrencyExposureInput[] | undefined
  /**
   * Symbols whose quote currency should not be read as exposure — the ETF bucket
   * of the allocation response. Absent simply means the caveat is not quantified.
   */
  fundSymbols?: ReadonlySet<string>
  isLoading?: boolean
  isError?: boolean
}

export function CurrencyExposureCard({
  positions,
  fundSymbols,
  isLoading,
  isError,
}: CurrencyExposureCardProps) {
  const curSym = useCurrencySymbol()
  const { baseCurrency } = useBaseCurrency()
  const [open, setOpen] = useState(false)

  const exposure = useMemo(
    () => computeCurrencyExposure(positions ?? [], fundSymbols),
    [positions, fundSymbols],
  )

  // `undefined` is "not loaded", not "nothing held" — the distinction the
  // rebalance panel got wrong and that `e2e/errors` caught.
  const unavailable = isError || positions === undefined
  const foreign = foreignQuotedPct(exposure, baseCurrency)

  const summary = unavailable
    ? "Couldn't load positions, so currency exposure can't be measured."
    : foreign === null
      ? 'Nothing priced yet, so there is no exposure to report.'
      : `${foreign.toFixed(0)}% of the book is quoted outside ${baseCurrency}.`

  return (
    <Card>
      <CollapsibleCardHeader
        open={open}
        onToggle={() => setOpen((v) => !v)}
        title="Currency Exposure"
        description={summary}
        contentId="currency-exposure-panel"
      />
      {open && (
        <CardContent id="currency-exposure-panel" className="space-y-4">
          {isLoading ? (
            <div className="h-24 bg-muted animate-pulse rounded" />
          ) : unavailable ? (
            <p className="text-sm text-red-800 dark:text-red-200">
              Couldn't load your positions — the backend didn't respond, so currency exposure
              is unavailable. It retries automatically.
            </p>
          ) : exposure.rows.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No priced positions, so there is nothing to break down.
            </p>
          ) : (
            <>
              {/*
                The limit is stated up front rather than in a footnote, because a
                reader who takes these rows as FX risk will be wrong by the size of
                the fund sleeve. See lib/currencyExposure.ts for why the split is
                not re-attributed.
              */}
              {exposure.lookThroughCount > 0 && (
                <p className="text-sm text-amber-700 dark:text-amber-400">
                  {exposure.lookThroughPct.toFixed(1)}% of the book sits in{' '}
                  {exposure.lookThroughCount} fund{exposure.lookThroughCount === 1 ? '' : 's'},
                  whose quote currency need not be its economic exposure — a EUR-listed S&amp;P
                  500 tracker is quoted in EUR and carries USD risk. Those rows are counted
                  where they trade, not re-attributed: the look-through data maps regions, not
                  currencies.
                </p>
              )}
              {exposure.unpricedCount > 0 && (
                <p className="text-sm text-amber-700 dark:text-amber-400">
                  {exposure.unpricedCount} position(s) have no cached price, so they carry no
                  currency weight here and the total is understated.
                </p>
              )}

              <ScrollableTable label="Portfolio value by quote currency">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b text-left text-muted-foreground">
                      <th scope="col" className="py-2 pr-4 font-medium">Currency</th>
                      <th scope="col" className="py-2 pr-4 text-right font-medium">Value</th>
                      <th scope="col" className="py-2 pr-4 text-right font-medium">Share</th>
                      <th scope="col" className="py-2 pr-4 text-right font-medium">Positions</th>
                      <th scope="col" className="py-2 text-right font-medium">of which funds</th>
                    </tr>
                  </thead>
                  <tbody>
                    {exposure.rows.map((row) => (
                      <tr key={row.currency} className="border-b last:border-0">
                        <td className="py-2 pr-4 font-medium">
                          {row.currency}
                          {row.currency === baseCurrency.toUpperCase() && (
                            <span className="ml-2 text-xs font-normal text-muted-foreground">
                              base
                            </span>
                          )}
                        </td>
                        <td className="py-2 pr-4 text-right tabular-nums">
                          {curSym}
                          {Math.round(row.marketValue).toLocaleString('en-US')}
                        </td>
                        <td className="py-2 pr-4 text-right tabular-nums">
                          {row.pct.toFixed(1)}%
                        </td>
                        <td className="py-2 pr-4 text-right tabular-nums">
                          {row.positionCount}
                        </td>
                        <td className="py-2 text-right tabular-nums text-muted-foreground">
                          {row.fundCount === 0 ? '—' : row.fundCount}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </ScrollableTable>
              <p className="text-xs text-muted-foreground">
                Grouped by the currency each listing trades in, valued in {baseCurrency} at each
                position's own date. This is quote currency, not a hedging position — for a direct
                holding the two coincide, for a fund they need not.
              </p>
            </>
          )}
        </CardContent>
      )}
    </Card>
  )
}
