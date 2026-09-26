<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import Paginator from 'primevue/paginator'
import OfferCard from '../components/OfferCard.vue'
import WishlistButton from '../components/WishlistButton.vue'
import { api } from '../lib/api'
import { buyer, matchingProfile } from '../lib/buyer'

const router = useRouter()
const data = ref({ results: [], total: 0, per_page: 24 })
const loading = ref(false)
const error = ref('')
const page = ref(1)
let requestId = 0
const profile = computed(() => buyer.profile)

async function load() {
  const request = ++requestId
  error.value = ''
  if (!profile.value) { loading.value = false; data.value = { results: [], total: 0, per_page: 24 }; return }
  loading.value = true
  const current = matchingProfile(profile.value)
  router.replace({ query: { city: current.city } })
  try {
    const result = await api.matches(current, page.value)
    if (request === requestId) data.value = result
  } catch (e) {
    if (request === requestId) error.value = e.message || 'Офертите не могат да бъдат заредени.'
  } finally { if (request === requestId) loading.value = false }
}
function onPage(event) { page.value = event.page + 1; load() }
watch(profile, () => { page.value = 1; load() }, { immediate: true })
</script>

<template>
  <div class="page buyer-page matches-page">
    <div class="buyer-heading spread wrap">
      <div><span class="buyer-eyebrow">ПОДБРАНИ ПО ТВОИТЕ ИЗИСКВАНИЯ</span><h1>Оферти за теб</h1>
        <p v-if="profile" class="muted">{{ profile.city === 'sofia' ? 'София' : profile.city === 'varna' ? 'Варна' : profile.city }} · {{ profile.rooms ? `${profile.rooms} стаи · ` : '' }}{{ profile.deal === 'rent' ? 'под наем' : 'за покупка' }} · {{ data.total }} подходящи оферти</p>
      </div>
      <RouterLink :to="{ name: 'buyer-profile', query: { city: profile?.city || $route.query.city } }" class="buyer-button">{{ profile ? 'Редактирай профила' : 'Създай профил' }}</RouterLink>
    </div>
    <section v-if="!profile" class="card empty">
      <i class="pi pi-user" aria-hidden="true" /><h2>Първо ни кажи какво търсиш</h2>
      <p class="muted">Избери град, стаи, бюджет и нуждите на домакинството си в таб „Потребител“.</p>
      <RouterLink :to="{ name: 'buyer-profile', query: $route.query }" class="buyer-button primary">Попълни профила</RouterLink>
    </section>
    <div v-else-if="loading" class="loading" role="status">Търсим офертите за теб…</div>
    <section v-else-if="error" class="card empty" role="alert"><p>{{ error }}</p><button class="buyer-button" @click="load">Опитай отново</button></section>
    <section v-else-if="!data.results.length" class="card empty">
      <i class="pi pi-search" aria-hidden="true" /><h2>Все още няма подходящи оферти</h2>
      <p class="muted">{{ profile.city === 'sofia' ? 'В момента няма активни оферти за София, които отговарят на профила ти. Профилът е запазен; проверявай тук, когато добавим нови оферти.' : 'Няма активни оферти по тези изисквания. Можеш да разшириш бюджета, кварталите или характеристиките.' }}</p>
      <RouterLink :to="{ name: 'buyer-profile', query: { city: profile.city } }" class="buyer-button">Редактирай изискванията</RouterLink>
    </section>
    <template v-else>
      <p class="buyer-hint">Първо показваме офертите с най-много потвърдени изисквания. „За проверка“ означава, че агенцията не е публикувала нужната информация.</p>
      <div class="match-grid">
        <article v-for="offer in data.results" :key="offer.id" class="buyer-match-card">
          <OfferCard :offer="offer" />
          <div class="buyer-match-details">
            <div class="spread wrap"><strong>{{ offer.match.confidence }}% от изискванията са потвърдени</strong><WishlistButton :offer="offer" /></div>
            <p class="small"><span class="buyer-confirmed">Съвпада:</span> {{ offer.match.reasons.join(' · ') }}</p>
            <p v-if="offer.match.unknown.length" class="small buyer-unconfirmed">За проверка: {{ offer.match.unknown.join(' · ') }}</p>
            <p v-else class="small buyer-confirmed">Всички избрани изисквания са потвърдени в данните на обявата.</p>
            <p v-if="profile.pets !== 'none' && profile.deal === 'sale'" class="small muted">Преди оглед потвърди правилата на сградата за домашни любимци.</p>
          </div>
        </article>
      </div>
      <Paginator :rows="data.per_page" :total-records="data.total" :first="(page - 1) * data.per_page" @page="onPage" />
    </template>
  </div>
</template>

<style scoped>
.matches-page { max-width: 1480px; }
.match-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1rem;
}
.buyer-match-card { display: flex; flex-direction: column; min-width: 0; }
.buyer-match-card :deep(.offer) {
  flex: 1;
  grid-template-columns: minmax(0, 1fr);
  grid-template-rows: auto 1fr;
}
.buyer-match-card :deep(.offer-media) { aspect-ratio: 16 / 10; min-height: 0; }
.buyer-match-card :deep(.offer-head) { flex-direction: column; gap: 0.5rem; }
.buyer-match-card :deep(.offer-title) {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  white-space: normal;
  min-height: 2.7em;
}
.buyer-match-card :deep(.offer-price-box) { text-align: left; }
.buyer-match-details .spread { flex-direction: column; align-items: flex-start; }
.buyer-match-details strong { font-size: 0.85rem; }
@media (max-width: 1099px) {
  .match-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
}
@media (max-width: 699px) {
  .match-grid { grid-template-columns: minmax(0, 1fr); }
}
</style>
