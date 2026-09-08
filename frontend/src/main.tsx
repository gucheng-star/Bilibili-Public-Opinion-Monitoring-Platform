import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { HashRouter } from 'react-router-dom'
import './index.css'
import App from './App.tsx'
import { initializeDesktopRuntime, isDesktopRuntime } from './services/desktop.ts'
import AppErrorBoundary from './components/AppErrorBoundary.tsx'
import { NoticeProvider } from './components/NoticeProvider.tsx'
import { initializeDevDiagnostics, installGlobalErrorHandlers, reportDiagnosticError } from './services/devDiagnostics.ts'
import { initializeTheme } from './theme.ts'

initializeTheme()

if (import.meta.env.DEV) {
  installGlobalErrorHandlers()
}

void initializeDesktopRuntime()
  .catch(error => {
    reportDiagnosticError('startup.failed', error)
    return null
  })
  .finally(() => {
    if (import.meta.env.DEV && !isDesktopRuntime()) {
      void initializeDevDiagnostics()
    }
    createRoot(document.getElementById('root')!).render(
      <StrictMode>
        <HashRouter>
          <AppErrorBoundary>
            <NoticeProvider>
              <App />
            </NoticeProvider>
          </AppErrorBoundary>
        </HashRouter>
      </StrictMode>,
    )
  })
