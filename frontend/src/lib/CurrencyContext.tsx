import { createContext, useContext, useMemo, type ReactNode } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { api } from './api'
import { formatCurrency as formatCurrencyUtil, currencySymbol as currencySymbolUtil } from './utils'

interface CurrencyContextValue {
  baseCurrency: string
  supportedCurrencies: string[]
  setBaseCurrency: (currency: string) => void
  isUpdating: boolean
  /** Set when the last currency change failed — the dropdown silently reverts otherwise. */
  updateError: string | null
  /**
   * True when `baseCurrency` is the fallback rather than the account's setting.
   *
   * `/api/settings` is fetched with `staleTime: Infinity` because the value only
   * changes through our own mutation — which means a single failed fetch is not a
   * blip but sticky for the session. Without this flag the app then renders every
   * money figure with a `€` while the numbers behind them are whatever the account
   * actually uses, and nothing anywhere says so. The figures are not wrong; the
   * label is, which is worse than an obvious gap.
   */
  currencyIsAssumed: boolean
}

const FALLBACK_CURRENCY = 'EUR'
const DEFAULT_SUPPORTED = ['EUR', 'CHF', 'USD']

const CurrencyContext = createContext<CurrencyContextValue>({
  baseCurrency: FALLBACK_CURRENCY,
  supportedCurrencies: DEFAULT_SUPPORTED,
  setBaseCurrency: () => {},
  isUpdating: false,
  updateError: null,
  currencyIsAssumed: false,
})

export function CurrencyProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()

  const { data, isError: settingsFailed } = useQuery({
    queryKey: ['settings'],
    queryFn: () => api.getSettings(),
    staleTime: Infinity,
  })

  const mutation = useMutation({
    mutationFn: (currency: string) => api.updateBaseCurrency(currency),
    onSuccess: (updated) => {
      queryClient.setQueryData(['settings'], updated)
      // Every money figure depends on the base currency — refetch all data so
      // portfolio, dividends, allocation, benchmarks, etc. re-render in the new base.
      queryClient.invalidateQueries()
    },
  })

  // Memoized on primitives: this context is consumed at the Dashboard root, so a
  // fresh object identity per provider render re-rendered the entire tree
  // (including the ~800-point chart) even when nothing changed.
  const { mutate } = mutation
  const value = useMemo<CurrencyContextValue>(() => ({
    baseCurrency: data?.base_currency ?? FALLBACK_CURRENCY,
    supportedCurrencies: data?.supported_currencies ?? DEFAULT_SUPPORTED,
    setBaseCurrency: (currency: string) => mutate(currency),
    isUpdating: mutation.isPending,
    updateError: mutation.isError
      ? 'Currency change failed — still showing the previous currency.'
      : null,
    // Only once the fetch has actually failed. While it is still in flight the
    // fallback is a placeholder, not a claim, and alarming on first paint would
    // train the reader to ignore it. A later refetch that errors keeps `data`,
    // so this stays false — the label is still the account's own.
    currencyIsAssumed: settingsFailed && data === undefined,
  }), [data, mutate, mutation.isPending, mutation.isError, settingsFailed])

  return <CurrencyContext.Provider value={value}>{children}</CurrencyContext.Provider>
}

export function useBaseCurrency() {
  return useContext(CurrencyContext)
}

/** Returns a formatter bound to the current base currency (override optional). */
export function useFormatCurrency() {
  const { baseCurrency } = useContext(CurrencyContext)
  return (value: number, currencyOverride?: string) =>
    formatCurrencyUtil(value, currencyOverride ?? baseCurrency)
}

/** Returns the short symbol/prefix for the current base currency. */
export function useCurrencySymbol() {
  const { baseCurrency } = useContext(CurrencyContext)
  return currencySymbolUtil(baseCurrency)
}
