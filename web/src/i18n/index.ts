import i18n from 'i18next';
import { initReactI18next } from 'react-i18next';
import zh from './zh.json';
import en from './en.json';
import { readSetting, writeSetting } from '../utils/storage';

const saved = readSetting('lang') ?? undefined;

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
  writeSetting('lang', lang);
}

export default i18n;
