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
}

const DEFAULT_SUPPORTED = ['EUR', 'CHF', 'USD']

const CurrencyContext = createContext<CurrencyContextValue>({
  baseCurrency: 'EUR',
  supportedCurrencies: DEFAULT_SUPPORTED,
  setBaseCurrency: () => {},
  isUpdating: false,
  updateError: null,
})

export function CurrencyProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()

  const { data } = useQuery({
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
    baseCurrency: data?.base_currency ?? 'EUR',
    supportedCurrencies: data?.supported_currencies ?? DEFAULT_SUPPORTED,
    setBaseCurrency: (currency: string) => mutate(currency),
    isUpdating: mutation.isPending,
    updateError: mutation.isError
      ? 'Currency change failed — still showing the previous currency.'
      : null,
  }), [data, mutate, mutation.isPending, mutation.isError])

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
