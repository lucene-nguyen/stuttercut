// UI errors go to the API log (POST /api/logs), so they show in Diagnostics and the export.

export interface UiErrorReport {
  level: 'ERROR' | 'WARN'
  message: string
  stack?: string
  component_stack?: string
  url?: string
}

const cap = (s: string | undefined, n: number) => (s === undefined ? undefined : s.slice(0, n))

/** The request body; sizes capped to what the API accepts. */
export function errorReport(error: Error, componentStack?: string, url?: string): UiErrorReport {
  return {
    level: 'ERROR',
    message: cap(`${error.name}: ${error.message}`, 2000)!,
    stack: cap(error.stack, 8000),
    component_stack: cap(componentStack, 8000),
    url: cap(url, 500),
  }
}

export async function reportUiError(error: Error, componentStack?: string): Promise<void> {
  try {
    await fetch('/api/logs', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(errorReport(error, componentStack, window.location.hash || '/')),
    })
  } catch {
    // the API is down: nothing more we can do from the browser
  }
}
