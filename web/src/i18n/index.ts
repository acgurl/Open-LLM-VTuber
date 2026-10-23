import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import zh from './zh.json';
import en from './en.json';

const saved = (() => {
  try {
    return localStorage.getItem('ollmvt.lang') ?? undefined;
  } catch {
    return undefined;
  }
})();

void i18n.use(initReactI18next).init({
  resources: {
    zh: { translation: zh },
    en: { translation: en },
  },
  lng: saved ?? (navigator.language.toLowerCase().startsWith('zh') ? 'zh' : 'en'),
  fallbackLng: 'zh',
  interpolation: { escapeValue: false },
});

export function setLanguage(lang: string) {
  void i18n.changeLanguage(lang);
  try {
    localStorage.setItem('ollmvt.lang', lang);
  } catch {
    /* ignore */
  }
}

export default i18n;
