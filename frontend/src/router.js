import { createRouter, createWebHistory } from 'vue-router'
import { rememberedCity, rememberCity } from './lib/city'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'search', component: () => import('./views/SearchView.vue') },
    { path: '/imot/:id', name: 'offer', component: () => import('./views/OfferView.vue') },
    { path: '/agencii', name: 'agencies', component: () => import('./views/AgenciesView.vue') },
    { path: '/user', name: 'buyer-profile', component: () => import('./views/ProfileView.vue') },
    { path: '/for-you', name: 'buyer-matches', component: () => import('./views/MatchesView.vue') },
    { path: '/wishlist', name: 'buyer-wishlist', component: () => import('./views/WishlistView.vue') },
  ],
  scrollBehavior: () => ({ top: 0 }),
})

router.beforeEach((to) => {
  if (!to.query.city) return { ...to, query: { ...to.query, city: rememberedCity() }, replace: true }
  if (typeof to.query.city !== 'string') return { ...to, query: { ...to.query, city: 'varna' }, replace: true }
  rememberCity(to.query.city)
})

export default router
