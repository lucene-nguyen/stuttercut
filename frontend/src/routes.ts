/** Hash routes: #/ (Upload & jobs), #/review/<id>, #/diagnostics. */
export function parseRoute(hash: string): { page: 'jobs' | 'review' | 'diagnostics'; id?: string } {
  const m = hash.match(/^#\/review\/([\w-]+)/)
  if (m) return { page: 'review', id: m[1] }
  if (hash.startsWith('#/diagnostics')) return { page: 'diagnostics' }
  return { page: 'jobs' }
}
