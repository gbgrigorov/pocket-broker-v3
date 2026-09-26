<script setup>
import { onMounted, ref, watch } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import IconField from 'primevue/iconfield'
import InputIcon from 'primevue/inputicon'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import { api } from './lib/api'
import { buyer } from './lib/buyer'

const route = useRoute()
const router = useRouter()
const search = ref('')
const stats = ref(null)
const cities = ref([])
let statsRequest = 0

const tabs = [
  { label: 'Потребител', to: { name: 'buyer-profile' }, key: 'buyer-profile' },
  { label: 'Оферти за теб', to: { name: 'buyer-matches' }, key: 'buyer-matches' },
  { label: 'Желани имоти', to: { name: 'buyer-wishlist' }, key: 'buyer-wishlist' },
  { label: 'Оферти', to: { name: 'search' }, key: 'search' },
  { label: 'Агенции', to: { name: 'agencies' }, key: 'agencies' },
]

function submitSearch() {
  router.push({ name: 'search', query: { ...route.query, q: search.value.trim(), page: 1 } })
}

onMounted(async () => {
  try { cities.value = (await api.cities()).cities } catch { /* search reports failures */ }
})

watch(() => route.query.city, async (city) => {
  const request = ++statsRequest
  stats.value = null
  if (!city) return
  try {
    const result = await api.stats({ city })
    if (request === statsRequest) stats.value = result
  } catch { /* the header degrades quietly */ }
}, { immediate: true })

function switchCity(city) {
  if (route.name === 'buyer-profile' || route.name === 'buyer-matches') {
    router.push({ name: 'buyer-profile', query: { city } })
    return
  }
  router.push({ name: 'search', query: { city, deal: route.query.deal || 'sale' } })
}

function tabCity(tab) {
  return ['buyer-profile', 'buyer-matches'].includes(tab.key) ? buyer.profile?.city || route.query.city : route.query.city
}
</script>

<template>
  <header class="shell-top">
    <div class="shell-top-inner">
      <RouterLink :to="{ name: 'search', query: { city: route.query.city } }" class="brand">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 28 28" width="26" height="26">
            <path d="M4 15.5 14 7l10 8.5v1.5a1 1 0 0 1-1 1h-5.5v-6h-7v6H5a1 1 0 0 1-1-1z"
                  fill="#2b7cb8" />
            <path d="M2 22c3.5-2.2 6.5-2.2 10 0s6.5 2.2 10 0" stroke="#7db2da"
                  stroke-width="2" fill="none" stroke-linecap="round" />
          </svg>
        </span>
        <span class="brand-text">Pocket Broker</span>
      </RouterLink>

      <label class="city-switch">
        <span class="tiny muted">Град</span>
        <Select :model-value="route.query.city" :options="cities" option-label="name_bg"
                option-value="slug" aria-label="Град" size="small" @update:model-value="switchCity" />
      </label>

      <form class="shell-search" @submit.prevent="submitSearch">
        <IconField>
          <InputIcon class="pi pi-search" />
          <InputText v-model="search" placeholder="квартал, ключова дума…" size="small" fluid />
        </IconField>
      </form>

      <!-- What the index contains. It is the claim the product rests on, so it
           belongs in the chrome rather than in a footnote. -->
      <div v-if="stats" class="shell-stats small muted">
        <span><b class="mono-num">{{ stats.offers.toLocaleString('bg-BG') }}</b> оферти</span>
        <span class="dot">·</span>
        <span><b>{{ stats.agencies }}</b> проверени агенции</span>
      </div>
    </div>

    <nav class="shell-tabs">
      <div class="shell-tabs-inner">
        <RouterLink
          v-for="tab in tabs" :key="tab.key" :to="{ ...tab.to, query: { city: tabCity(tab) } }"
          class="tab" :class="{ 'tab-on': route.name === tab.key }"
        >{{ tab.label }}<span v-if="tab.key === 'buyer-wishlist' && buyer.wishlist.length" class="pill">{{ buyer.wishlist.length }}</span></RouterLink>
        <span class="tab-gap" />
        <a class="tab tab-out" href="/admin/sourcing/offer/">Администрация<i class="pi pi-external-link" /></a>
      </div>
    </nav>
  </header>

  <main><RouterView /></main>
</template>

<style scoped>
.shell-top { position: sticky; top: 0; z-index: 20; background: #fff; border-bottom: 1px solid var(--line); }
.shell-top-inner {
  display: flex; align-items: center; gap: 1.25rem;
  max-width: 1480px; margin: 0 auto; padding: 0.65rem 1.5rem;
}
.brand { display: flex; align-items: center; gap: 0.55rem; flex: 0 0 auto; }
.brand-mark { display: flex; }
.brand-text { font-weight: 700; font-size: 0.98rem; color: var(--navy); letter-spacing: -0.015em; }
.shell-search { flex: 1 1 auto; max-width: 420px; }
.shell-stats { margin-left: auto; display: flex; align-items: center; gap: 0.4rem; white-space: nowrap; }
.shell-stats b { color: var(--ink); }
.dot { color: var(--ink-faint); }
.city-switch { display: flex; align-items: center; gap: 0.4rem; }
@media (max-width: 640px) {
  .shell-top-inner { flex-wrap: wrap; gap: 0.6rem; padding: 0.65rem 1rem; }
  .shell-search { flex-basis: 100%; max-width: none; }
  .city-switch { margin-left: auto; }
}

.shell-tabs { border-top: 1px solid var(--line); background: #fff; }
.shell-tabs-inner {
  display: flex; align-items: stretch; gap: 0.15rem;
  max-width: 1480px; margin: 0 auto; padding: 0 1.5rem; overflow-x: auto;
}
.tab {
  display: flex; align-items: center; gap: 0.35rem; padding: 0.6rem 0.75rem;
  font-size: 0.82rem; font-weight: 500; color: var(--ink-soft);
  border-bottom: 2px solid transparent; white-space: nowrap;
}
.tab:hover { color: var(--ink); }
.tab-on { color: #1f6299; border-bottom-color: #2b7cb8; font-weight: 600; }
.tab-gap { flex: 1 1 auto; }
.tab-out { color: var(--ink-faint); }
.tab-out i { font-size: 0.6rem; }

@media (max-width: 860px) { .shell-stats { display: none; } }
</style>
