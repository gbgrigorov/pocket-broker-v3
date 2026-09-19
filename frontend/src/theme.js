// The palette from the broker-crm design comp, as a PrimeVue preset.
// Shared deliberately: this and the CRM look at the same stock.
//
// Aura is the base because it already matches the comp's shape language --
// 6px radii, thin borders, flat surfaces, no shadows on cards. Only the primary
// ramp is replaced: the comp's blue is the deep Black Sea navy of the logo, not
// Aura's default emerald.

import { definePreset } from '@primeuix/themes'
import Aura from '@primeuix/themes/aura'

export const MarketPreset = definePreset(Aura, {
  semantic: {
    primary: {
      50: '#eff6fb',
      100: '#d6e8f5',
      200: '#aed0ea',
      300: '#7db2da',
      400: '#4f92c7',
      500: '#2b7cb8',
      600: '#1f6299',
      700: '#1a4f7d',
      800: '#173f64',
      900: '#13314e',
      950: '#0c2036',
    },
    colorScheme: {
      light: {
        surface: {
          0: '#ffffff',
          50: '#f8fafc',
          100: '#f1f5f9',
          200: '#e2e8f0',
          300: '#cbd5e1',
          400: '#94a3b8',
          500: '#64748b',
          600: '#475569',
          700: '#334155',
          800: '#1e293b',
          900: '#0f172a',
          950: '#020617',
        },
        formField: { background: '#ffffff', borderColor: '#dbe3ec' },
      },
    },
  },
  components: {
    card: { body: { padding: '1.15rem' } },
    button: { root: { paddingY: '0.45rem' } },
  },
})

// How complete a listing is. Agencies publish patchy data and the card says so
// rather than hiding it -- the same rule the filters follow: a missing value
// never removes a listing, it costs confidence.
export const COMPLETENESS = {
  full: { label: 'пълни данни', bg: '#dcfce7', fg: '#15803d' },
  partial: { label: 'непълни данни', bg: '#ffedd5', fg: '#c2410c' },
  thin: { label: 'оскъдни данни', bg: '#fef3c7', fg: '#a16207' },
}

export function completenessOf(missing = []) {
  if (!missing.length) return COMPLETENESS.full
  return missing.length <= 2 ? COMPLETENESS.partial : COMPLETENESS.thin
}
