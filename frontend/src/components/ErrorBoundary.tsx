import { Component, type ErrorInfo, type ReactNode } from 'react'

import { reportUiError } from '../api/report'

/** Catches render errors anywhere below, logs them through POST /api/logs, shows a way out. */
export default class ErrorBoundary extends Component<
  { children: ReactNode },
  { error: Error | null }
> {
  state = { error: null as Error | null }

  static getDerivedStateFromError(error: Error) {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    void reportUiError(error, info.componentStack ?? undefined)
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <main className="page">
        <div
          role="alert"
          className="alert"
          style={{ flexDirection: 'column', alignItems: 'flex-start' }}
        >
          <strong>Something went wrong on this screen.</strong>
          <span>
            The error was written to the log (Diagnostics → Logs). Your review decisions are saved.
          </span>
        </div>
        <div className="row">
          <button className="btn primary" onClick={() => window.location.reload()}>
            Reload
          </button>
          <a className="btn" href="#/diagnostics" onClick={() => this.setState({ error: null })}>
            Open Diagnostics
          </a>
        </div>
      </main>
    )
  }
}
