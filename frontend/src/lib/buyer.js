import { reactive } from 'vue'

const PROFILE_KEY = 'pb3.buyer.profile.v1'
const WISHLIST_KEY = 'pb3.buyer.wishlist.v1'

export function emptyProfile(city = 'sofia') {
  return { city, deal: 'sale', kind: 'apartment', rooms: '2', price_min: '', price_max: '',
    area_min: '', neighbourhoods: [], family: '', children: '0', pets: 'none', features: [] }
}

function read(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback } catch { return fallback }
}
function validProfile(value) {
  return value && typeof value === 'object' && typeof value.city === 'string'
    && Array.isArray(value.neighbourhoods) && Array.isArray(value.features)
}
function cleanWishlist(value) {
  if (!Array.isArray(value)) return []
  const seen = new Set()
  return value.filter((item) => {
    if (!item || !Number.isSafeInteger(item.id) || item.id < 1 || seen.has(item.id)) return false
    seen.add(item.id)
    return true
  }).slice(0, 200).map(({ id, title }) => ({ id, title: typeof title === 'string' ? title : 'Имот' }))
}

const storedProfile = read(PROFILE_KEY, null)
export const buyer = reactive({
  profile: validProfile(storedProfile) ? { ...emptyProfile(storedProfile.city), ...storedProfile } : null,
  wishlist: cleanWishlist(read(WISHLIST_KEY, [])),
  storageError: '',
})

function persist(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value))
    buyer.storageError = ''
    return true
  } catch {
    buyer.storageError = 'Браузърът не позволява запазване. Разрешете съхранението и опитайте отново.'
    return false
  }
}
export function saveProfile(profile) {
  const value = JSON.parse(JSON.stringify(profile))
  if (!persist(PROFILE_KEY, value)) return false
  buyer.profile = value
  return true
}
export function clearProfile() {
  if (!persist(PROFILE_KEY, null)) return false
  buyer.profile = null
  return true
}
export function isSaved(id) { return buyer.wishlist.some((item) => item.id === id) }
export function toggleSaved(offer) {
  let next
  if (isSaved(offer.id)) next = buyer.wishlist.filter((item) => item.id !== offer.id)
  else {
    if (buyer.wishlist.length >= 200) {
      buyer.storageError = 'Можете да запазите до 200 имота. Премахнете имот, за да добавите нов.'
      return
    }
    next = [{ id: offer.id, title: offer.title || 'Имот' }, ...buyer.wishlist]
  }
  if (persist(WISHLIST_KEY, next)) buyer.wishlist = next
}

// Household context is kept on this device; the API needs only property requirements.
export function matchingProfile(profile) {
  const { family, children, ...requirements } = profile
  return requirements
}

window.addEventListener('storage', (event) => {
  if (event.key === PROFILE_KEY || event.key === null) {
    const profile = read(PROFILE_KEY, null)
    buyer.profile = validProfile(profile) ? { ...emptyProfile(profile.city), ...profile } : null
  }
  if (event.key === WISHLIST_KEY || event.key === null) buyer.wishlist = cleanWishlist(read(WISHLIST_KEY, []))
})
