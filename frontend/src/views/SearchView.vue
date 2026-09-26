<script setup>
import { reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import Button from 'primevue/button'
import InputText from 'primevue/inputtext'
import Select from 'primevue/select'
import Paginator from 'primevue/paginator'
import Checkbox from 'primevue/checkbox'
import OfferCard from '../components/OfferCard.vue'
import WishlistButton from '../components/WishlistButton.vue'
import { api } from '../lib/api'

const route = useRoute()
const router = useRouter()

const SORTS = [
  { label: 'Най-нови', value: 'newest' },
  { label: 'Цена — възходящо', value: 'price_asc' },
  { label: 'Цена — низходящо', value: 'price_desc' },
  { label: 'Площ — низходящо', value: 'area_desc' },
  { label: '€/м² — възходящо', value: 'sqm_asc' },
]

const f = reactive({
  city: route.query.city,
  neighbourhood: route.query.neighbourhood || null,
  deal: route.query.deal || 'sale',
  q: route.query.q || '',
  kind: route.query.kind || null,
  price_min: route.query.price_min || '',
  price_max: route.query.price_max || '',
  area_min: route.query.area_min || '',
  beds: route.query.beds || '',
  agency: route.query.agency || null,
  build: route.query.build || null,
  with_photo: route.query.with_photo === '1',
  sort: route.query.sort || 'newest',
  page: Number(route.query.page || 1),
})

const data = ref({ results: [], total: 0, per_page: 24 })
const facets = ref({ kinds: [], agencies: [], total: 0 })
const loading = ref(true)
const neighbourhoods = ref([])
const error = ref('')
let requestId = 0

async function load() {
  const request = ++requestId
  loading.value = true
  error.value = ''
  const params = { ...f, with_photo: f.with_photo ? '1' : '' }
  try {
    const [rows, fac, places] = await Promise.all([
      api.offers(params), api.facets({ deal: f.deal, city: f.city }),
      api.neighbourhoods({ city: f.city }),
    ])
    if (request !== requestId) return
    data.value = rows
    facets.value = fac
    neighbourhoods.value = places.neighbourhoods
  } catch {
    if (request === requestId) {
      data.value = { results: [], total: 0, per_page: 24 }
      error.value = 'Офертите не могат да бъдат заредени. Опитайте отново.'
    }
  } finally {
    if (request === requestId) loading.value = false
  }
}

function navigate() {
  const params = { ...f, with_photo: f.with_photo ? '1' : '' }
  const query = Object.fromEntries(Object.entries(params).filter(([, v]) => v !== '' && v !== null))
  if (new URLSearchParams(query).toString() === new URLSearchParams(route.query).toString()) {
    load()
    return
  }
  router.push({
    query: Object.fromEntries(
      Object.entries({ ...params, page: f.page }).filter(([, v]) => v !== '' && v !== null)
    ),
  })
}

function apply() { f.page = 1; navigate() }
function reset() {
  Object.assign(f, { q: '', kind: null, price_min: '', price_max: '', area_min: '',
                     beds: '', agency: null, neighbourhood: null, build: null, with_photo: false, page: 1 })
  navigate()
}
function onPage(e) { f.page = e.page + 1; navigate() }

watch(() => route.query, (q) => {
  Object.assign(f, {
    city: q.city, neighbourhood: q.neighbourhood || null, deal: q.deal || 'sale',
    q: q.q || '', kind: q.kind || null, price_min: q.price_min || '', price_max: q.price_max || '',
    area_min: q.area_min || '', beds: q.beds || '', agency: q.agency || null,
    build: q.build || null, with_photo: q.with_photo === '1', sort: q.sort || 'newest',
    page: Number(q.page || 1),
  })
  load()
}, { immediate: true })
</script>

<template>
  <div class="page grid-side">
    <aside class="card rail">
      <div class="card-head"><h3>Филтри</h3>
        <Button label="изчисти" size="small" text @click="reset" />
      </div>
      <div class="rail-body">
        <div class="seg">
          <button :class="{ on: f.deal === 'sale' }" @click="f.deal = 'sale'; apply()">Продажби</button>
          <button :class="{ on: f.deal === 'rent' }" @click="f.deal = 'rent'; apply()">Наеми</button>
        </div>

        <div>
          <label class="field-label" for="neighbourhood">Квартал</label>
          <Select v-model="f.neighbourhood" :options="neighbourhoods" option-label="name_bg"
                  option-value="slug" input-id="neighbourhood" aria-label="Квартал" placeholder="всички" size="small"
                  show-clear fluid @update:model-value="apply" />
        </div>

        <div>
          <label class="field-label">Строителство</label>
          <div class="kindlist">
            <button
              v-for="b in facets.build || []" :key="b.key"
              :class="{ on: f.build === b.key }"
              @click="f.build = f.build === b.key ? null : b.key; apply()"
            >
              <span>{{ b.label }}</span><span class="n">{{ b.count }}</span>
            </button>
          </div>
        </div>

        <div>
          <label class="field-label">Вид имот</label>
          <div class="kindlist">
            <button
              v-for="k in facets.kinds" :key="k.key"
              :class="{ on: f.kind === k.key }"
              @click="f.kind = f.kind === k.key ? null : k.key; apply()"
            >
              <span>{{ k.label }}</span><span class="n">{{ k.count }}</span>
            </button>
          </div>
        </div>

        <div>
          <label class="field-label">Цена (€)</label>
          <div class="pair">
            <InputText v-model="f.price_min" placeholder="от" size="small" @keyup.enter="apply" />
            <InputText v-model="f.price_max" placeholder="до" size="small" @keyup.enter="apply" />
          </div>
        </div>

        <div class="pair">
          <div>
            <label class="field-label">Площ от (м²)</label>
            <InputText v-model="f.area_min" placeholder="60" size="small" fluid @keyup.enter="apply" />
          </div>
          <div>
            <label class="field-label">Спални от</label>
            <InputText v-model="f.beds" placeholder="2" size="small" fluid @keyup.enter="apply" />
          </div>
        </div>

        <div>
          <label class="field-label">Агенция</label>
          <Select
            v-model="f.agency" :options="facets.agencies" option-label="agency__name"
            option-value="agency__slug" placeholder="всички" size="small" show-clear fluid
            @update:model-value="apply"
          />
        </div>

        <label class="row small" style="cursor: pointer">
          <Checkbox v-model="f.with_photo" binary input-id="photo" @update:model-value="apply" />
          <span>само със снимка</span>
        </label>

        <Button label="Търси" icon="pi pi-search" size="small" @click="apply" />

        <p class="rail-note">
          В избрания град липсващите характеристики и неизвестният квартал остават в резултатите.
        </p>
      </div>
    </aside>

    <section>
      <div class="result-head">
        <h1>
          {{ f.deal === 'rent' ? 'Имоти под наем' : 'Имоти за продажба' }}
          <span class="count mono-num">· {{ data.total.toLocaleString('bg-BG') }}</span>
        </h1>
        <Select v-model="f.sort" :options="SORTS" option-label="label" option-value="value" size="small" @update:model-value="apply" />
      </div>

      <div v-if="loading" class="loading">
        <i class="pi pi-spin pi-spinner" style="font-size: 1.5rem; color: #94a3b8" />
      </div>

      <div v-else-if="error" class="card empty" role="alert">
        <p>{{ error }}</p><Button label="Опитай отново" @click="load" />
      </div>

      <div v-else-if="!data.results.length" class="card empty">
        <i class="pi pi-inbox" style="font-size: 1.6rem; color: #b6c2d1" />
        <p class="muted">Няма оферти, които отговарят на тези филтри.</p>
        <p v-if="f.city === 'sofia'" class="small faint">Подготвяме проверени оферти за София.</p>
        <Button label="Изчисти филтрите" size="small" severity="secondary" outlined @click="reset" />
      </div>

      <template v-else>
        <div class="list">
          <article v-for="o in data.results" :key="o.id" class="buyer-match-card">
            <OfferCard :offer="o" /><div class="buyer-match-details"><WishlistButton :offer="o" /></div>
          </article>
        </div>
        <Paginator
          :rows="data.per_page" :total-records="data.total"
          :first="(f.page - 1) * data.per_page" @page="onPage"
        />
      </template>
    </section>
  </div>
</template>
