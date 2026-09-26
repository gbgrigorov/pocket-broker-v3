<script setup>
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter, RouterLink } from 'vue-router'
import { api } from '../lib/api'
import { buyer, emptyProfile, saveProfile, matchingProfile, clearProfile } from '../lib/buyer'

const route = useRoute()
const router = useRouter()
const f = reactive(JSON.parse(JSON.stringify(buyer.profile || emptyProfile(route.query.city || 'sofia'))))
if (route.query.city && route.query.city !== f.city) {
  f.city = route.query.city
  f.neighbourhoods = []
}
const cities = ref([])
const places = ref([])
const features = ref([])
const loading = ref(true)
const saving = ref(false)
const error = ref('')
const placesError = ref('')
const placeQuery = ref('')
let placesRequest = 0
const visiblePlaces = computed(() => places.value.filter((p) => p.name_bg.toLocaleLowerCase('bg').includes(placeQuery.value.toLocaleLowerCase('bg'))))

async function loadPlaces() {
  const request = ++placesRequest
  places.value = []
  placesError.value = ''
  try {
    const result = await api.neighbourhoods({ city: f.city })
    if (request === placesRequest) places.value = result.neighbourhoods
  } catch {
    if (request === placesRequest) placesError.value = 'Кварталите не могат да бъдат заредени.'
  }
}
async function load() {
  loading.value = true
  error.value = ''
  try {
    const [cityData, options] = await Promise.all([api.cities(), api.buyerOptions()])
    cities.value = cityData.cities
    features.value = options.features
    await loadPlaces()
  } catch { error.value = 'Профилът не може да бъде зареден. Опитайте отново.' }
  finally { loading.value = false }
}

watch(() => f.city, (city) => {
  f.neighbourhoods = []
  placeQuery.value = ''
  router.replace({ query: { ...route.query, city } })
  loadPlaces()
})
watch(() => route.query.city, (city) => { if (city && city !== f.city) f.city = city })
async function save() {
  saving.value = true
  error.value = ''
  try {
    await api.matches(matchingProfile(f))
    if (saveProfile(f)) await router.push({ name: 'buyer-matches', query: { city: f.city } })
  } catch (e) { error.value = e.message || 'Профилът не може да бъде запазен.' }
  finally { saving.value = false }
}
function reset() {
  if (clearProfile()) Object.assign(f, emptyProfile(f.city))
}
onMounted(load)
</script>

<template>
  <div class="page buyer-page">
    <div class="buyer-heading">
      <span class="buyer-eyebrow">ТВОЯТ ДОМ, ТВОИТЕ НУЖДИ</span>
      <h1>Потребител · Какъв дом търсиш?</h1>
      <p class="muted">Опиши какво търсиш. Ще подредим подходящите оферти и ще покажем какво е потвърдено и какво трябва да попиташ.</p>
    </div>
    <div v-if="loading" class="loading" role="status">Зареждане на профила…</div>
    <div v-else-if="!cities.length" class="card empty">
      <p role="alert">{{ error }}</p><button class="buyer-button" @click="load">Опитай отново</button>
    </div>
    <form v-else class="buyer-layout" @submit.prevent="save">
      <div class="col buyer-sections">
        <section class="card card-body">
          <h2>1. Какво търсиш?</h2>
          <div class="buyer-fields">
            <label>Град<select v-model="f.city" aria-label="Град" required><option v-for="c in cities" :key="c.slug" :value="c.slug">{{ c.name_bg }}</option></select></label>
            <label>Искам да<select v-model="f.deal" aria-label="Искам да"><option value="sale">Купя</option><option value="rent">Наема</option></select></label>
            <label>Вид имот<select v-model="f.kind" aria-label="Вид имот"><option value="apartment">Апартамент</option><option value="house">Къща</option></select></label>
            <label>Брой стаи<select v-model="f.rooms" aria-label="Брой стаи"><option value="">Без предпочитание</option><option value="1">1 стая · студио / едностаен</option><option value="2">2 стаи · двустаен (1 спалня)</option><option value="3">3 стаи · тристаен (2 спални)</option><option value="4">4 стаи (3 спални)</option><option value="5">5 стаи (4 спални)</option></select></label>
            <label>{{ f.deal === 'rent' ? 'Месечен наем от (€)' : 'Бюджет от (€)' }}<input v-model="f.price_min" type="number" min="0" max="100000000" step="1" inputmode="numeric" placeholder="Без минимум" /></label>
            <label>{{ f.deal === 'rent' ? 'Месечен наем до (€)' : 'Бюджет до (€)' }}<input v-model="f.price_max" type="number" min="0" max="100000000" step="1" inputmode="numeric" placeholder="Без максимум" /></label>
            <label>Минимална площ (м²)<input v-model="f.area_min" type="number" min="0" max="100000" step="1" inputmode="numeric" placeholder="Без минимум" /></label>
          </div>
          <p class="small muted">Стаите включват дневната. Двустаен апартамент обикновено има дневна и една спалня.</p>
        </section>
        <section class="card card-body">
          <div class="spread wrap"><h2>2. В кои квартали?</h2><span class="small muted">{{ f.neighbourhoods.length ? `${f.neighbourhoods.length} избрани` : 'Всички квартали' }}</span></div>
          <label class="buyer-place-search">Намери квартал<input v-model="placeQuery" type="search" placeholder="Например Лозенец, Младост…" /></label>
          <div v-if="placesError" role="alert"><p>{{ placesError }}</p><button type="button" class="buyer-button" @click="loadPlaces">Опитай отново</button></div>
          <div v-else class="buyer-places">
            <label v-for="p in visiblePlaces" :key="p.slug" class="buyer-check"><input v-model="f.neighbourhoods" type="checkbox" :value="p.slug" />{{ p.name_bg }}</label>
            <p v-if="!visiblePlaces.length" class="muted">Няма намерени квартали.</p>
          </div>
          <button v-if="f.neighbourhoods.length" type="button" class="buyer-text-button" @click="f.neighbourhoods = []">Избери всички квартали</button>
          <p class="small muted">Ако агенцията не е посочила квартал, ще отбележим това в резултата.</p>
        </section>
        <section class="card card-body">
          <h2>3. За кого е домът?</h2>
          <div class="buyer-fields">
            <label>Домакинство / семейно положение<select v-model="f.family" aria-label="Домакинство / семейно положение"><option value="">Предпочитам да не посочвам</option><option value="alone">Живея сам / сама</option><option value="couple">Двойка</option><option value="family">Семейство</option><option value="shared">Със съквартиранти</option></select></label>
            <label>Деца<select v-model="f.children" aria-label="Деца"><option value="0">Без деца</option><option value="1">1 дете</option><option value="2">2 деца</option><option value="3">3 или повече</option><option value="">Предпочитам да не посочвам</option></select></label>
            <label>Домашни любимци<select v-model="f.pets" aria-label="Домашни любимци"><option value="none">Нямам</option><option value="cat">Котка</option><option value="dog">Куче</option><option value="other">Други домашни любимци</option></select></label>
          </div>
          <p v-if="f.family === 'family' || Number(f.children) > 0" class="buyer-hint">За семейство с деца можеш да добавиш асансьор или двор и да зададеш нужната площ. Избери характеристиките, които са важни за вас.</p>
          <p v-if="f.pets !== 'none'" class="buyer-hint">{{ f.deal === 'rent' ? 'При наем изключваме обяви, които изрично забраняват домашни любимци. Ако няма информация, показваме, че разрешението трябва да се потвърди.' : 'За покупка потвърди правилата на сградата за домашни любимци преди оглед.' }}</p>
          <p class="small muted">Семейните данни остават в този браузър. Съпоставянето използва избраните изисквания към имота.</p>
        </section>
        <section class="card card-body">
          <h2>4. Какво е важно за теб?</h2>
          <p class="small muted">Избраните характеристики са изисквания. Непосочена характеристика се отбелязва за проверка.</p>
          <div class="buyer-feature-list"><label v-for="feature in features" :key="feature.key" class="buyer-check"><input v-model="f.features" type="checkbox" :value="feature.key" />{{ feature.label }}</label></div>
        </section>
      </div>
      <aside class="card card-body buyer-summary">
        <h2>Твоето търсене</h2>
        <p><strong>{{ cities.find(c => c.slug === f.city)?.name_bg }}</strong> · {{ f.deal === 'rent' ? 'под наем' : 'за покупка' }}</p>
        <p>{{ f.kind === 'house' ? 'Къща' : 'Апартамент' }}{{ f.rooms ? ` · ${f.rooms} стаи` : '' }}</p>
        <p>{{ f.price_min || '0' }} – {{ f.price_max || 'без лимит' }} €{{ f.deal === 'rent' ? ' / месец' : '' }}</p>
        <p class="small muted">{{ f.neighbourhoods.length ? `${f.neighbourhoods.length} избрани квартала` : 'Всички квартали' }}</p>
        <p v-if="error" class="buyer-error" role="alert">{{ error }}</p>
        <p v-if="buyer.storageError" class="buyer-error" role="alert">{{ buyer.storageError }}</p>
        <button class="buyer-button primary" type="submit" :disabled="saving || !!placesError">{{ saving ? 'Проверяваме…' : 'Запази и виж офертите за теб' }}<i class="pi pi-arrow-right" aria-hidden="true" /></button>
        <RouterLink v-if="buyer.profile" :to="{ name: 'buyer-matches', query: { city: buyer.profile.city } }" class="buyer-text-button">Виж офертите по запазения профил</RouterLink>
        <button v-if="buyer.profile" type="button" class="buyer-text-button" @click="reset">Изтрий запазения профил</button>
        <p class="small muted">Профилът и желаните имоти се запазват в този браузър и са достъпни при следващо посещение. Изчистването на данните на браузъра ги премахва.</p>
      </aside>
    </form>
  </div>
</template>
