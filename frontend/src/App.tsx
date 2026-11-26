import { useEffect, useState } from 'react'

import { api } from './api/client'
import Header from './components/Header'
import Review from './features/review/Review'
import UploadJobs from './features/upload/UploadJobs'
import { parseRoute } from './routes'

export default function App() {
  const [hash, setHash] = useState(() =>
    typeof window === 'undefined' ? '' : window.location.hash,
  )
  const [platform, setPlatform] = useState('')
  useEffect(() => {
    const onHash = () => setHash(window.location.hash)
    window.addEventListener('hashchange', onHash)
    api.health().then(
      (h) => setPlatform(h.platform),
      () => setPlatform(''),
    )
    return () => window.removeEventListener('hashchange', onHash)
  }, [])
  const route = parseRoute(hash)

  if (route.page === 'review' && route.id) return <Review id={route.id} platform={platform} />
  return (
    <>
      <Header current={route.page} />
      {route.page === 'diagnostics' ? (
        <main className="page">
          <h1>Diagnostics</h1>
          <p className="muted">Metrics, traces and logs arrive with LEARNING-229.</p>
        </main>
      ) : (
        <UploadJobs platform={platform} />
      )}
    </>
  )
}
