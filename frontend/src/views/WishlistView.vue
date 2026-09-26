<script setup>
import { ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import OfferCard from '../components/OfferCard.vue'
import WishlistButton from '../components/WishlistButton.vue'
import { api } from '../lib/api'
import { buyer, toggleSaved } from '../lib/buyer'

const data = ref({ results: [], unavailable: [] })
const loading = ref(false)
const error = ref('')
let requestId = 0
async function load() {
  const request = ++requestId
  error.value = ''
  if (!buyer.wishlist.length) { data.value = { results: [], unavailable: [] }; loading.value = false; return }
  loading.value = true
  try {
    const result = await api.wishlist(buyer.wishlist.map((item) => item.id))
    if (request === requestId) data.value = result
  } catch (e) { if (request === requestId) error.value = e.message || 'Желаните имоти не могат да бъдат заредени.' }
  finally { if (request === requestId) loading.value = false }
}
watch(() => buyer.wishlist, load, { immediate: true })
</script>

<template>
  <div class="page buyer-page">
    <div class="buyer-heading spread wrap">
      <div class="grow">
        <span class="buyer-eyebrow">ДОМОВЕТЕ, КОИТО ХАРЕСВАШ</span><h1>Желани имоти · {{ buyer.wishlist.length }}</h1>
        <p class="muted">Твоят личен списък, запазен в този браузър. Проверяваме наличността и актуалната цена при отваряне.</p>
      </div>
      <button v-if="!loading && !error && data.results.length" type="button" class="buyer-button primary">
        <i class="pi pi-calendar" aria-hidden="true" />Заяви оглед за всички
      </button>
    </div>
    <p v-if="buyer.storageError" class="buyer-error" role="alert">{{ buyer.storageError }}</p>
    <section v-if="!buyer.wishlist.length" class="card empty">
      <i class="pi pi-heart" aria-hidden="true" /><h2>Запази първия си имот</h2>
      <p class="muted">Натисни „Добави в желани“ върху подходяща оферта, за да я намериш тук.</p>
      <RouterLink :to="{ name: 'buyer-matches', query: { city: buyer.profile?.city || $route.query.city } }" class="buyer-button primary">Виж офертите за теб</RouterLink>
    </section>
    <div v-else-if="loading" class="loading" role="status">Зареждане на желаните имоти…</div>
    <section v-else-if="error" class="card empty" role="alert"><p>{{ error }}</p><button class="buyer-button" @click="load">Опитай отново</button></section>
    <div v-else class="list">
      <article v-for="offer in data.results" :key="offer.id" class="buyer-match-card">
        <OfferCard :offer="offer" />
        <div class="buyer-match-details spread wrap">
          <WishlistButton :offer="offer" />
          <button type="button" class="buyer-button primary">
            <i class="pi pi-calendar" aria-hidden="true" />Заяви оглед
          </button>
        </div>
      </article>
      <article v-for="id in data.unavailable" :key="id" class="card card-body">
        <h2>{{ buyer.wishlist.find(item => item.id === id)?.title || 'Имот' }}</h2>
        <p class="muted">Тази оферта вече не е активна или не е налична. Запазили сме я в списъка ти.</p>
        <button class="buyer-button" @click="toggleSaved({ id })">Премахни от желани</button>
      </article>
    </div>
  </div>
</template>
