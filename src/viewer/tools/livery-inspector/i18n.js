import ja from './locales/ja.js';
import en from './locales/en.js';

const dictionaries = { ja, en };
const params = new URLSearchParams(window.location.search);
const requested = params.get('lang');
let language = requested && dictionaries[requested]
  ? requested
  : ((navigator.language || '').toLowerCase().startsWith('ja') ? 'ja' : 'en');

export function getLanguage() {
  return language;
}

export function setLanguage(value) {
  if (!dictionaries[value]) return;
  language = value;
  document.documentElement.lang = value;
  const url = new URL(window.location.href);
  if (value === 'ja') url.searchParams.delete('lang');
  else url.searchParams.set('lang', value);
  window.history.replaceState(null, '', url.toString());
}

export function t(key, values = {}) {
  const dictionary = dictionaries[language] || dictionaries.ja;
  const fallback = dictionaries.en[key] ?? key;
  let value = dictionary[key] ?? fallback;
  for (const [name, replacement] of Object.entries(values)) {
    value = value.replaceAll(`{${name}}`, String(replacement));
  }
  return value;
}

export function applyTranslations(root = document) {
  document.documentElement.lang = language;
  root.querySelectorAll('[data-i18n]').forEach(element => {
    element.textContent = t(element.dataset.i18n);
  });
  root.querySelectorAll('[data-i18n-title]').forEach(element => {
    element.title = t(element.dataset.i18nTitle);
  });
  root.querySelectorAll('[data-i18n-aria-label]').forEach(element => {
    element.setAttribute('aria-label', t(element.dataset.i18nAriaLabel));
  });
  document.title = t('app.title');
}
