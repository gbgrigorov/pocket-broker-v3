async function get(path, params = {}) {
  const clean = Object.fromEntries(
    Object.entries(params).filter(([, v]) => v !== '' && v !== null && v !== undefined)
  )
  const qs = new URLSearchParams(clean).toString()
  const res = await fetch(`/api${path}${qs ? `?${qs}` : ''}`)
  if (!res.ok) throw new Error(`${res.status} ${path}`)
  return res.json()
}

export const api = {
  offers: (p) => get('/offers/', p),
  offer: (id) => get(`/offers/${id}/`),
  facets: (p) => get('/facets/', p),
  agencies: () => get('/agencies/'),
  stats: () => get('/stats/'),
}

export function eur(n) {
  if (n === null || n === undefined) return '—'
  return new Intl.NumberFormat('bg-BG', {
    style: 'currency', currency: 'EUR', maximumFractionDigits: 0,
  }).format(n)
}

// A dash, never a zero or a blank. An unpublished number and a number that is
// genuinely zero are different things, and the card must not blur them.
export function num(value, suffix = '') {
  if (value === null || value === undefined || value === '') return '—'
  return `${new Intl.NumberFormat('bg-BG').format(value)}${suffix}`
}
