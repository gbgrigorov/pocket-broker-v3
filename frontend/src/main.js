import { createApp } from 'vue'
import { createPinia } from 'pinia'
import PrimeVue from 'primevue/config'
import Tooltip from 'primevue/tooltip'

import 'primeicons/primeicons.css'
import './style.css'

import App from './App.vue'
import router from './router'
import { MarketPreset } from './theme'

createApp(App)
  .use(createPinia())
  .use(router)
  .use(PrimeVue, {
    theme: { preset: MarketPreset, options: { darkModeSelector: '.dark' } },
    locale: {
      clear: 'изчисти',
      emptyMessage: 'няма резултати',
      emptySearchMessage: 'няма резултати',
      emptySelectionMessage: 'няма избор',
    },
  })
  .directive('tooltip', Tooltip)
  .mount('#app')
