// URL context wins; local storage is only a preference, never a search result.
export function rememberedCity() {
  try { return localStorage.getItem('pocket-broker-city') || 'varna' }
  catch { return 'varna' }
}

export function rememberCity(city) {
  try { localStorage.setItem('pocket-broker-city', city) } catch { /* private browsing */ }
}
