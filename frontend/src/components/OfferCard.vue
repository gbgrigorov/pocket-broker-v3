<script setup>
import { computed, ref, watch } from 'vue'
import { RouterLink } from 'vue-router'
import { eur, num } from '../lib/api'
import { completenessOf } from '../theme'

const props = defineProps({ offer: { type: Object, required: true } })

// What the agency did not publish, in words the reader knows.
const LABELS = {
  price_eur: 'цена', area_m2: 'площ', bedrooms: 'спални', floor: 'етаж',
}

const perM2 = computed(() => {
  const o = props.offer
  if (o.price_per_m2) return Math.round(o.price_per_m2)
  if (o.price && o.area) return Math.round(o.price / o.area)
  return null
})
const tone = computed(() => completenessOf(props.offer.missing))
// Акт 16 means habitable now; anything earlier means waiting, and "пред"
// anything means it has not got there yet.
const stageTone = computed(() =>
  props.offer.stage === 'Акт 16' ? 'done' : 'building')

// A picture that will not load must fall back to the placeholder, not spill its
// alt text across the card. Agency image URLs rot, and a listing whose photo
// has gone is still a listing worth showing.
const broken = ref(false)
watch(() => props.offer.id, () => { broken.value = false })
</script>

<template>
  <RouterLink :to="{ name: 'offer', params: { id: offer.id }, query: { city: offer.city || $route.query.city } }" class="offer">
    <div class="offer-media">
      <img
        v-if="offer.image && !broken" :src="offer.image" :alt="offer.title"
        loading="lazy" @error="broken = true"
      />
      <div v-else class="offer-media-empty"><i class="pi pi-image" /></div>
      <span class="media-deal">{{ offer.deal === 'rent' ? 'наем' : 'продажба' }}</span>
      <span class="media-agency truncate" :title="offer.agency.name">
        {{ offer.agency.name }}
      </span>
      <!-- "Пред Акт 16" is not a finished building; it is the opposite. A buyer
           has to see that before the price, not after a viewing. -->
      <span v-if="offer.stage" class="media-stage" :class="stageTone">{{ offer.stage }}</span>
      <span v-else-if="offer.new_build" class="media-stage new">ново строителство</span>
    </div>

    <div class="offer-main">
      <header class="offer-head">
        <div class="grow">
          <h4 class="offer-title truncate">{{ offer.title || 'без заглавие' }}</h4>
          <p class="offer-where small muted">
            {{ offer.location || 'населено място не е посочено' }}
            <span v-if="!offer.neighbourhood" class="tiny faint"> · кварталът не е уточнен</span>
          </p>
        </div>
        <div class="offer-price-box">
          <p class="offer-price mono-num">
            {{ offer.price ? eur(offer.price) : 'по запитване' }}
          </p>
          <p v-if="perM2" class="offer-permetre tiny faint mono-num">{{ perM2 }} €/м²</p>
        </div>
      </header>

      <div class="offer-specs small muted">
        <span><i class="pi pi-expand" /> {{ num(offer.area, ' м²') }}</span>
        <span><i class="pi pi-home" /> {{ offer.bedrooms ?? '—' }} спални</span>
        <span><i class="pi pi-building" /> {{ offer.floor ?? '—' }} етаж</span>
        <span v-if="offer.kind" class="tag">{{ offer.kind }}</span>
      </div>

      <footer class="offer-foot">
        <!-- Which agency is publishing this is the first thing to know about an
             offer here: the whole index is built on who is trusted enough to be
             in it. An unlabelled tag among other tags did not say that. -->
        <span class="offer-agency">
          <i class="pi pi-building" />
          <span class="faint">агенция</span>
          <b class="truncate">{{ offer.agency.name }}</b>
        </span>
        <span class="pill" :style="{ background: tone.bg, color: tone.fg }">{{ tone.label }}</span>
        <span v-if="offer.missing.length" class="tiny faint offer-missing">
          няма: {{ offer.missing.map((m) => LABELS[m] || m).join(', ') }}
        </span>
      </footer>
    </div>
  </RouterLink>
</template>

<style scoped>
.offer {
  display: grid; grid-template-columns: 200px minmax(0, 1fr);
  background: #fff; border: 1px solid var(--line); border-radius: 10px;
  overflow: hidden; transition: border-color 0.12s, box-shadow 0.12s;
}
.offer:hover { border-color: #c7d7e6; box-shadow: 0 1px 3px rgba(15, 23, 42, 0.06); }

.offer-media { position: relative; background: #eef2f7; min-height: 156px; overflow: hidden; }
/* Absolute, so a tall photo cannot stretch the row. The card's height is set
   by its text; the image crops to whatever that leaves. */
.offer-media img { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; display: block; }
.offer-media-empty { display: grid; place-items: center; height: 100%; color: #b6c2d1; font-size: 1.4rem; }
.media-deal {
  position: absolute; left: 6px; top: 6px; padding: 0.1rem 0.4rem; border-radius: 4px;
  background: rgba(15, 23, 42, 0.62); color: #fff; font-size: 0.65rem; font-weight: 600;
}
.media-stage {
  position: absolute; right: 6px; top: 6px;
  padding: 0.12rem 0.4rem; border-radius: 4px;
  font-size: 0.63rem; font-weight: 700; color: #fff;
}
.media-stage.done { background: #15803d; }
.media-stage.building { background: #c2410c; }
.media-stage.new { background: #1f6299; }
.media-agency {
  position: absolute; left: 6px; right: 6px; bottom: 6px;
  padding: 0.12rem 0.4rem; border-radius: 4px;
  background: rgba(15, 23, 42, 0.62); color: #fff;
  font-size: 0.65rem; font-weight: 600; text-align: center;
}

.offer-main { padding: 0.8rem 0.9rem; display: flex; flex-direction: column; gap: 0.45rem; }
.offer-head { display: flex; align-items: flex-start; gap: 0.9rem; }
.offer-title { font-size: 0.9rem; line-height: 1.35; }
.offer-where { margin: 0.15rem 0 0; }

.offer-price-box { text-align: right; flex: 0 0 auto; }
.offer-price { margin: 0; font-size: 1.15rem; font-weight: 700; color: var(--navy); white-space: nowrap; }
.offer-permetre { margin: 0.1rem 0 0; }

.offer-specs { display: flex; align-items: center; gap: 0.85rem; flex-wrap: wrap; }
.offer-specs i { font-size: 0.68rem; margin-right: 0.2rem; }

.offer-foot {
  margin-top: auto; display: flex; align-items: center; gap: 0.5rem; flex-wrap: wrap;
  padding-top: 0.5rem; border-top: 1px solid var(--line);
}
.offer-agency {
  display: inline-flex; align-items: center; gap: 0.3rem;
  font-size: 0.78rem; min-width: 0; max-width: 100%;
}
.offer-agency i { font-size: 0.7rem; color: var(--ink-faint); }
.offer-agency .faint { font-size: 0.7rem; }
.offer-agency b { color: var(--navy); font-weight: 600; }
.offer-missing { margin-left: 0.1rem; }

@media (max-width: 640px) {
  .offer { grid-template-columns: minmax(0, 1fr); }
  .offer-head { flex-direction: column; gap: 0.3rem; }
  .offer-price-box { text-align: left; }
}
</style>
