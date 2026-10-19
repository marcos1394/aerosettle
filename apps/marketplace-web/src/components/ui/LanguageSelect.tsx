import { useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { useI18n, type Locale } from '../../app/i18n';
export function LanguageSelect() {
  const { locale, setLocale, t } = useI18n();
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({ top: 0, left: 0 });
  const trigger = useRef<HTMLButtonElement>(null);
  const menu = useRef<HTMLDivElement>(null);
  const id = useId();
  function close(restore = false) {
    setOpen(false);
    if (restore) trigger.current?.focus({ preventScroll: true });
  }
  useLayoutEffect(() => {
    if (!open) return;
    const rect = trigger.current!.getBoundingClientRect();
    setPosition({
      top: rect.bottom + 10,
      left: Math.max(12, Math.min(window.innerWidth - 244, rect.right - 232)),
    });
    menu.current
      ?.querySelector<HTMLButtonElement>('[aria-checked="true"]')
      ?.focus({ preventScroll: true });
    const outside = (e: PointerEvent) => {
      if (
        !trigger.current?.contains(e.target as Node) &&
        !menu.current?.contains(e.target as Node)
      )
        setOpen(false);
    };
    const dismiss = () => setOpen(false);
    document.addEventListener('pointerdown', outside);
    window.addEventListener('resize', dismiss);
    window.addEventListener('scroll', dismiss, true);
    return () => {
      document.removeEventListener('pointerdown', outside);
      window.removeEventListener('resize', dismiss);
      window.removeEventListener('scroll', dismiss, true);
    };
  }, [open]);
  return (
    <div className="language-select">
      <button
        ref={trigger}
        type="button"
        className="language-trigger"
        aria-label={t('Language')}
        aria-haspopup="menu"
        aria-expanded={open}
        aria-controls={open ? id : undefined}
        onClick={() => setOpen((value) => !value)}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            setOpen(true);
          }
          if (e.key === 'Escape') close();
        }}
      >
        <svg
          viewBox="0 0 24 24"
          width="16"
          height="16"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          aria-hidden="true"
        >
          <circle cx="12" cy="12" r="9" />
          <ellipse cx="12" cy="12" rx="4" ry="9" />
          <path d="M3 12h18" />
        </svg>
        <span>{locale.toUpperCase()}</span>
        <svg
          className="language-chevron"
          viewBox="0 0 16 16"
          width="12"
          height="12"
          fill="none"
          stroke="currentColor"
          strokeWidth="1.5"
          aria-hidden="true"
        >
          <path d="m4 6 4 4 4-4" />
        </svg>
      </button>
      {open &&
        createPortal(
          <div
            ref={menu}
            id={id}
            className="language-menu"
            style={position}
            role="menu"
            aria-label={t('Language')}
            onBlur={(e) => {
              if (
                !e.currentTarget.contains(e.relatedTarget as Node) &&
                e.relatedTarget !== trigger.current
              )
                close();
            }}
            onKeyDown={(e) => {
              const items = Array.from(
                menu.current?.querySelectorAll<HTMLButtonElement>(
                  '[role="menuitemradio"]'
                ) ?? []
              );
              const index = items.indexOf(
                document.activeElement as HTMLButtonElement
              );
              if (e.key === 'Escape') {
                e.preventDefault();
                e.stopPropagation();
                close(true);
              } else if (
                e.key === 'ArrowDown' ||
                e.key === 'ArrowUp' ||
                e.key === 'Home' ||
                e.key === 'End'
              ) {
                e.preventDefault();
                const next =
                  e.key === 'Home'
                    ? 0
                    : e.key === 'End'
                      ? items.length - 1
                      : (index +
                          (e.key === 'ArrowDown' ? 1 : items.length - 1)) %
                        items.length;
                items[next]?.focus();
              } else if (e.key === 'Tab') close();
            }}
          >
            <p className="language-menu-title">{t('Choose your language')}</p>
            {(['en', 'es'] as Locale[]).map((code) => (
              <button
                type="button"
                role="menuitemradio"
                aria-checked={locale === code}
                tabIndex={-1}
                key={code}
                onClick={() => {
                  setLocale(code);
                  close(true);
                }}
              >
                <span className="language-code">{code.toUpperCase()}</span>
                <span lang={code}>
                  {code === 'en' ? 'English' : 'Español'}
                  <small>
                    {t(code === 'en' ? 'English language' : 'Spanish language')}
                  </small>
                </span>
                <span className="language-check" aria-hidden="true">
                  {locale === code ? '✓' : ''}
                </span>
              </button>
            ))}
            <span className="language-menu-note">
              {t('Saved for your next visit')}
            </span>
          </div>,
          document.body
        )}
    </div>
  );
}
