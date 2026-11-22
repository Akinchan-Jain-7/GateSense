import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import { en } from './en'
import { hi } from './hi'

export type Language = 'en' | 'hi'
const KEY = 'gatesense.lang'

function savedLanguage(): Language {
  try {
    return localStorage.getItem(KEY) === 'hi' ? 'hi' : 'en'
  } catch {
    return 'en'
  }
}

void i18n.use(initReactI18next).init({
  resources: { en: { translation: en }, hi: { translation: hi } },
  lng: savedLanguage(),
  fallbackLng: 'en',
  interpolation: { escapeValue: false }, // React already escapes
})

export function setLanguage(language: Language): void {
  void i18n.changeLanguage(language)
  try {
    localStorage.setItem(KEY, language)
  } catch {
    // ignore
  }
}

export default i18n
