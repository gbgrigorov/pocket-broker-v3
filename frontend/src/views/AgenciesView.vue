<script setup>
import { ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import { api } from '../lib/api'

const rows = ref([])
const loading = ref(true)
const route = useRoute()
const error = ref('')
let requestId = 0
watch(() => route.query.city, async (city) => {
  const request = ++requestId
  loading.value = true
  rows.value = []
  error.value = ''
  try {
    const result = await api.agencies({ city })
    if (request === requestId) rows.value = result.agencies
  } catch {
    if (request === requestId) error.value = 'Агенциите не могат да бъдат заредени.'
  } finally { if (request === requestId) loading.value = false }
}, { immediate: true })
</script>

<template>
  <div class="page">
    <div class="result-head">
      <div>
        <h1>Проверени агенции</h1>
        <p class="muted small" style="margin: 0.25rem 0 0; max-width: 62ch">
          Индексират се само агенции, приети по публично правило: членство в НСНИ,
          или оценка над 4.0 с реална история от отзиви. Списъкът на изключените
          също е публичен.
        </p>
      </div>
    </div>

    <div v-if="loading" class="loading">
      <i class="pi pi-spin pi-spinner" style="font-size: 1.5rem; color: #94a3b8" />
    </div>

    <p v-else-if="error" role="alert">{{ error }}</p>
    <p v-else-if="!rows.length" class="muted">Все още няма активни оферти от агенции в този град.</p>
    <div v-else class="grid-3">
      <article v-for="a in rows" :key="a.slug" class="card">
        <div class="card-head">
          <h3 class="truncate">{{ a.name }}</h3>
          <span class="pill" style="background: #eff6fb; color: #1f6299">
            {{ a.live.toLocaleString('bg-BG') }}
          </span>
        </div>
        <div class="card-body col">
          <p class="tiny muted agency-note">{{ a.notes }}</p>
          <div class="row small" style="margin-top: auto">
            <RouterLink :to="{ name: 'search', query: { city: route.query.city, agency: a.slug } }" style="color: #1f6299; font-weight: 600">
              Офертите ѝ
            </RouterLink>
            <a v-if="a.website" :href="a.website" target="_blank" rel="noopener" class="faint">
              сайт <i class="pi pi-external-link" style="font-size: 0.6rem" />
            </a>
          </div>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.card { display: flex; flex-direction: column; }
.card-body { flex: 1; }
.agency-note {
  line-height: 1.5; display: -webkit-box; -webkit-line-clamp: 5;
  -webkit-box-orient: vertical; overflow: hidden;
}
</style>
