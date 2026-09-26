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
  agencies: (p) => get('/agencies/', p),
  stats: (p) => get('/stats/', p),
  cities: () => get('/cities/'),
  neighbourhoods: (p) => get('/neighbourhoods/', p),
  buyerOptions: () => get('/buyer/options/'),
  matches: (profile, page = 1) => post('/buyer/matches/', { profile, page }),
  wishlist: (ids) => post('/buyer/wishlist/', { ids }),
}

let csrfRequest
async function post(path, payload) {
  if (!csrfRequest) csrfRequest = get('/buyer/options/').catch((error) => {
    csrfRequest = null
    throw error
  })
  const { csrf_token } = await csrfRequest
  const res = await fetch(`/api${path}`, {
    method: 'POST', credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf_token },
    body: JSON.stringify(payload),
  })
  if (res.status === 403) {
    csrfRequest = null
    throw new Error('Сесията е обновена. Опитайте отново.')
  }
  let data
  try { data = await res.json() } catch {
    throw new Error('Сървърът не може да отговори. Опитайте отново.')
  }
  if (!res.ok) {
    throw new Error(data.error || 'Заявката не може да бъде изпълнена. Опитайте отново.')
  }
  return data
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
