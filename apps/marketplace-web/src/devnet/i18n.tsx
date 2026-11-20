import { createContext, useCallback, useContext, useEffect, useMemo, useState,
  type ReactNode } from 'react';
export type Locale = 'en' | 'es';
const Context = createContext<{ locale: Locale; setLocale: (value: Locale) => void } | null>(null);
export function LanguageProvider({ children }: { children: ReactNode }) {
  const [locale, setLocale] = useState<Locale>(() => {
    try { return localStorage.getItem('conatus.locale') === 'es' ? 'es' : 'en'; }
    catch { return 'en'; }
  });
  useEffect(() => {
    document.documentElement.lang = locale;
    try { localStorage.setItem('conatus.locale', locale); } catch { /* session only */ }
  }, [locale]);
  const value = useMemo(() => ({ locale, setLocale }), [locale]);
  return <Context.Provider value={value}>{children}</Context.Provider>;
}
export function useCopy() {
  const value = useContext(Context);
  if (!value) throw Error('Devnet LanguageProvider required');
  return useCallback((en: string, es: string) => value.locale === 'es' ? es : en, [value.locale]);
}
export function LanguageSelect() {
  const value = useContext(Context);
  if (!value) throw Error('Devnet LanguageProvider required');
  return <label className="devnet-language-select">
    <span className="sr-only">Language / Idioma</span>
    <select aria-label="Language / Idioma" value={value.locale}
      onChange={(event) => value.setLocale(event.target.value as Locale)}>
      <option value="en">EN</option><option value="es">ES</option>
    </select>
  </label>;
}
