import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';
import messages from './messages.json';
export type Locale = 'en' | 'es';
type Values = Record<string, string | number>;
const catalogs: Record<string, { en: string; es: string }> = messages;
export function translate(locale: Locale, key: string, values: Values = {}) {
  const template = catalogs[key]?.[locale] ?? key;
  return template.replace(/\{(\w+)\}/g, (match, name: string) =>
    String(values[name] ?? match)
  );
}
const Context = createContext<{
  locale: Locale;
  setLocale: (locale: Locale) => void;
  t: (key: string, values?: Values) => string;
} | null>(null);
export function LanguageProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(() => {
    try {
      return localStorage.getItem('conatus.locale') === 'es' ? 'es' : 'en';
    } catch {
      return 'en';
    }
  });
  useEffect(() => {
    document.documentElement.lang = locale;
    try {
      localStorage.setItem('conatus.locale', locale);
    } catch {
      /* Language remains available for this session. */
    }
  }, [locale]);
  const t = useCallback(
    (key: string, values?: Values) => translate(locale, key, values),
    [locale]
  );
  const value = useMemo(() => ({ locale, setLocale, t }), [locale, t]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useI18n() {
  const context = useContext(Context);
  if (!context) throw new Error('LanguageProvider is required.');
  return context;
}
/** Inline bilingual copy: `c('English', 'Español')`. */
export function useCopy() {
  const { locale } = useI18n();
  return useCallback(
    (en: string, es: string) => (locale === 'es' ? es : en),
    [locale]
  );
}
export { LanguageSelect } from '../components/ui/LanguageSelect';
