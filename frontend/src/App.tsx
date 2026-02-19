import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { Dashboard } from './components/Dashboard'
import { ThemeProvider } from './components/ThemeProvider'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      retry: 1,
      staleTime: 5 * 60 * 1000, // 5 minutes
    },
  },
})

function App() {
  return (
    <ThemeProvider defaultTheme="light" storageKey="ibkr-theme">
      <QueryClientProvider client={queryClient}>
        <div className="min-h-screen bg-background">
          <Dashboard />
        </div>
      </QueryClientProvider>
    </ThemeProvider>
  )
}

export default App
