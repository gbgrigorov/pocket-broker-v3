import { createRouter, createWebHistory } from 'vue-router'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'search', component: () => import('./views/SearchView.vue') },
    { path: '/imot/:id', name: 'offer', component: () => import('./views/OfferView.vue') },
    { path: '/agencii', name: 'agencies', component: () => import('./views/AgenciesView.vue') },
  ],
  scrollBehavior: () => ({ top: 0 }),
})
