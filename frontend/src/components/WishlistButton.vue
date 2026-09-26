<script setup>
import { buyer, isSaved, toggleSaved } from '../lib/buyer'
defineProps({ offer: { type: Object, required: true } })
</script>

<template>
  <div class="wishlist-control">
    <button type="button" class="buyer-button wishlist-button" :class="{ saved: isSaved(offer.id) }"
            :aria-pressed="isSaved(offer.id)" @click="toggleSaved(offer)">
      <i :class="isSaved(offer.id) ? 'pi pi-heart-fill' : 'pi pi-heart'" aria-hidden="true" />
      {{ isSaved(offer.id) ? 'Премахни от желани' : 'Добави в желани' }}
    </button>
    <span v-if="buyer.storageError" class="buyer-error small" role="alert">{{ buyer.storageError }}</span>
  </div>
</template>
