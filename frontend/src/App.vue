<script setup>
import { onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute, useRouter } from 'vue-router'
import IconField from 'primevue/iconfield'
import InputIcon from 'primevue/inputicon'
import InputText from 'primevue/inputtext'
import { api } from './lib/api'

const route = useRoute()
const router = useRouter()
const search = ref('')
const stats = ref(null)

const tabs = [
  { label: 'Оферти', to: { name: 'search' }, key: 'search' },
  { label: 'Агенции', to: { name: 'agencies' }, key: 'agencies' },
]

function submitSearch() {
  router.push({ name: 'search', query: { ...route.query, q: search.value.trim(), page: 1 } })
}

onMounted(async () => {
  try { stats.value = await api.stats() } catch { /* the header degrades quietly */ }
})
</script>

<template>
  <header class="shell-top">
    <div class="shell-top-inner">
      <RouterLink :to="{ name: 'search' }" class="brand">
        <span class="brand-mark" aria-hidden="true">
          <svg viewBox="0 0 28 28" width="26" height="26">
            <path d="M4 15.5 14 7l10 8.5v1.5a1 1 0 0 1-1 1h-5.5v-6h-7v6H5a1 1 0 0 1-1-1z"
                  fill="#2b7cb8" />
            <path d="M2 22c3.5-2.2 6.5-2.2 10 0s6.5 2.2 10 0" stroke="#7db2da"
                  stroke-width="2" fill="none" stroke-linecap="round" />
          </svg>
        </span>
        <span class="brand-text">Varna Market</span>
      </RouterLink>

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
          v-for="tab in tabs" :key="tab.key" :to="tab.to"
          class="tab" :class="{ 'tab-on': route.name === tab.key }"
        >{{ tab.label }}</RouterLink>
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
