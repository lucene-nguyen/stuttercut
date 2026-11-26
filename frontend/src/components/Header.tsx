export function Logo() {
  return (
    <span className="logo" aria-hidden="true">
      <svg
        width="18"
        height="18"
        viewBox="0 0 24 24"
        fill="none"
        stroke="#0E1014"
        strokeWidth="2.2"
        strokeLinecap="round"
        strokeLinejoin="round"
      >
        <circle cx="6" cy="6" r="3" />
        <circle cx="6" cy="18" r="3" />
        <path d="M20 4 8.12 15.88M14.47 14.48 20 20M8.12 8.12 12 12" />
      </svg>
    </span>
  )
}

export default function Header({ current }: { current: 'jobs' | 'review' | 'diagnostics' }) {
  return (
    <header className="topbar">
      <div className="brand">
        <Logo />
        StutterCut
        <nav className="nav" aria-label="Main">
          <a href="#/" aria-current={current === 'jobs' ? 'page' : undefined}>
            Projects
          </a>
          <a href="#/diagnostics" aria-current={current === 'diagnostics' ? 'page' : undefined}>
            Diagnostics
          </a>
        </nav>
      </div>
      <div className="pill">
        <span className="dot" aria-hidden="true" />
        Local · nothing leaves this computer
      </div>
    </header>
  )
}
