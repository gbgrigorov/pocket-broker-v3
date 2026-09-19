<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { RouterLink, useRoute } from 'vue-router'
import Button from 'primevue/button'
import { api, eur, num } from '../lib/api'
import { completenessOf } from '../theme'

const route = useRoute()
const offer = ref(null)
const loading = ref(true)
const index = ref(0)
const broken = ref(false)

const images = computed(() => offer.value?.images || [])
const tone = computed(() => completenessOf(offer.value?.missing || []))
const perM2 = computed(() => {
  const o = offer.value
  if (!o) return null
  if (o.price_per_m2) return Math.round(o.price_per_m2)
  return o.price && o.area ? Math.round(o.price / o.area) : null
})

async function load() {
  loading.value = true
  index.value = 0
  broken.value = false
  try { offer.value = await api.offer(route.params.id) } finally { loading.value = false }
}
function step(d) {
  const n = images.value.length
  if (!n) return
  broken.value = false
  index.value = (index.value + d + n) % n
}
onMounted(load)
watch(() => route.params.id, load)
</script>

<template>
  <div v-if="loading" class="page loading">
    <i class="pi pi-spin pi-spinner" style="font-size: 1.5rem; color: #94a3b8" />
  </div>

  <div v-else-if="offer" class="page grid-2">
    <section class="card">
      <div class="detail-media">
        <img
          v-if="images[index] && !broken" :src="images[index]" :alt="offer.title"
          @error="broken = true"
        />
        <div v-else class="detail-media-empty"><i class="pi pi-image" /></div>
        <template v-if="images.length > 1">
          <button class="media-nav prev" aria-label="Предишна" @click="step(-1)">
            <i class="pi pi-chevron-left" />
          </button>
          <button class="media-nav next" aria-label="Следваща" @click="step(1)">
            <i class="pi pi-chevron-right" />
          </button>
          <span class="media-count"><i class="pi pi-camera" /> {{ index + 1 }}/{{ images.length }}</span>
        </template>
      </div>

      <div class="card-body">
        <div class="spread wrap" style="align-items: flex-start">
          <div class="grow">
            <h1 style="font-size: 1.15rem">{{ offer.title }}</h1>
            <p class="muted small" style="margin: 0.25rem 0 0">
              {{ offer.location || 'населено място не е посочено' }}
            </p>
          </div>
          <div style="text-align: right">
            <p class="mono-num detail-price">{{ offer.price ? eur(offer.price) : 'по запитване' }}</p>
            <p v-if="perM2" class="tiny faint mono-num" style="margin: 0.1rem 0 0">{{ perM2 }} €/м²</p>
          </div>
        </div>

        <dl class="detail-specs">
          <div><dt class="tiny faint">Площ</dt><dd class="mono-num">{{ num(offer.area, ' м²') }}</dd></div>
          <div><dt class="tiny faint">Спални</dt><dd class="mono-num">{{ offer.bedrooms ?? '—' }}</dd></div>
          <div><dt class="tiny faint">Етаж</dt><dd class="mono-num">{{ offer.floor ?? '—' }}</dd></div>
          <div><dt class="tiny faint">Вид</dt><dd>{{ offer.kind || '—' }}</dd></div>
          <div><dt class="tiny faint">Сделка</dt><dd>{{ offer.deal === 'rent' ? 'наем' : 'продажба' }}</dd></div>
          <div><dt class="tiny faint">Агенция</dt><dd>{{ offer.agency.name }}</dd></div>
        </dl>

        <p class="row" style="margin: 0.9rem 0 0">
          <span class="pill" :style="{ background: tone.bg, color: tone.fg }">{{ tone.label }}</span>
          <span v-if="offer.missing.length" class="tiny faint">
            агенцията не е публикувала: {{ offer.missing.join(', ') }}
          </span>
        </p>

        <Button
          as="a" :href="offer.url" target="_blank" rel="noopener" class="detail-cta"
          label="Отвори обявата при агенцията" icon="pi pi-external-link" size="small"
        />
      </div>
    </section>

    <aside class="col">
      <div v-if="offer.siblings.length" class="card">
        <div class="card-head"><h3>Същият имот при {{ offer.siblings.length + 1 }} агенции</h3></div>
        <div class="card-body">
          <p v-if="offer.spread" class="spread-delta mono-num">
            разлика {{ eur(offer.spread) }}
          </p>
          <ul class="spread-list">
            <li class="spread-row on">
              <span class="truncate">{{ offer.agency.name }}</span>
              <b class="mono-num">{{ offer.price ? eur(offer.price) : '—' }}</b>
            </li>
            <li v-for="s in offer.siblings" :key="s.id" class="spread-row">
              <RouterLink class="truncate" :to="`/imot/${s.id}`">{{ s.agency.name }}</RouterLink>
              <b class="mono-num">{{ s.price ? eur(s.price) : '—' }}</b>
            </li>
          </ul>
          <p class="tiny faint" style="margin: 0.6rem 0 0">
            Групирани по съвпадение на локация, площ, етаж и спални. Цените не се обединяват —
            разликата между агенциите е това, което си струва да се види.
          </p>
        </div>
      </div>

      <div class="card">
        <div class="card-head"><h3>Произход</h3></div>
        <div class="card-body small muted">
          <p style="margin: 0">
            Взета директно от сайта на {{ offer.agency.name }}.
            Не индексираме портали.
          </p>
          <p v-if="offer.first_seen" class="tiny faint" style="margin: 0.5rem 0 0">
            Първо видяна {{ new Date(offer.first_seen).toLocaleDateString('bg-BG') }}
          </p>
        </div>
      </div>
    </aside>
  </div>
</template>

<style scoped>
.detail-media { position: relative; background: #eef2f7; aspect-ratio: 16 / 9; overflow: hidden; }
.detail-media img { width: 100%; height: 100%; object-fit: cover; display: block; }
.detail-media-empty { display: grid; place-items: center; height: 100%; color: #b6c2d1; font-size: 2rem; }
.media-nav {
  position: absolute; top: 50%; transform: translateY(-50%);
  width: 30px; height: 30px; display: grid; place-items: center;
  border: 0; border-radius: 50%; background: rgba(15, 23, 42, 0.45); color: #fff; cursor: pointer;
}
.prev { left: 10px; } .next { right: 10px; }
.media-count {
  position: absolute; left: 10px; bottom: 10px; padding: 0.12rem 0.4rem; border-radius: 4px;
  background: rgba(15, 23, 42, 0.6); color: #fff; font-size: 0.68rem;
}
.detail-price { margin: 0; font-size: 1.5rem; font-weight: 700; color: var(--navy); }
.detail-specs {
  display: grid; grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
  gap: 0.7rem; margin: 1rem 0 0; padding: 0.85rem 0 0; border-top: 1px solid var(--line);
}
.detail-specs dt { margin-bottom: 0.15rem; }
.detail-specs dd { margin: 0; font-weight: 600; font-size: 0.875rem; }
.detail-cta { margin-top: 1rem; }
.spread-delta { margin: 0 0 0.6rem; font-size: 1.15rem; font-weight: 700; color: var(--check); }
.spread-list { list-style: none; margin: 0; padding: 0; }
.spread-row {
  display: flex; justify-content: space-between; gap: 0.75rem;
  padding: 0.45rem 0; border-bottom: 1px solid var(--line); font-size: 0.8125rem;
}
.spread-row:last-child { border-bottom: 0; }
.spread-row.on { font-weight: 600; }
</style>
