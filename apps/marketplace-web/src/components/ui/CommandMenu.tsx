import { useEffect, useRef, useState } from 'react';
import { useNavigate } from 'react-router';
import { useCopy, useI18n } from '../../app/i18n';
import { Icon } from './index';
const commands = [
  ['Mission Control', 'Mission Control', '/app', 'grid'],
  ['Economy & Conatus Index', 'Economía e Índice Conatus', '/app/economy', 'economy'],
  ['Agents marketplace', 'Marketplace de agentes', '/app/agents', 'agents'],
  ['Register a machine', 'Registrar una máquina', '/app/agents/register', 'bolt'],
  ['Mission marketplace', 'Marketplace de misiones', '/app/missions', 'missions'],
  ['Post a mission', 'Publicar una misión', '/app/missions/new', 'plus'],
  ['Mission planner', 'Planificador de misión', '/app/planner', 'target'],
  ['My fleet', 'Mi flota', '/app/fleet', 'fleet'],
  ['Treasury', 'Tesorería', '/app/wallet', 'wallet'],
  ['Network activity', 'Actividad de red', '/app/activity', 'activity'],
  ['Ecosystem & integrations', 'Ecosistema e integraciones', '/ecosystem', 'globe'],
  ['Conatus Journal', 'Conatus Journal', '/journal', 'spark'],
  ['Product roadmap', 'Hoja de ruta', '/roadmap', 'trophy'],
  ['Settings', 'Configuración', '/app/settings', 'settings'],
] as const;
export function CommandMenu() {
  const { t } = useI18n();
  const c = useCopy();
  const navigate = useNavigate();
  const dialog = useRef<HTMLDialogElement>(null);
  const input = useRef<HTMLInputElement>(null);
  const [query, setQuery] = useState('');
  const results = commands.filter(([en, es]) =>
    `${en} ${es}`.toLocaleLowerCase().includes(query.trim().toLocaleLowerCase())
  );
  function show() {
    setQuery('');
    dialog.current?.showModal();
    input.current?.focus();
  }
  useEffect(() => {
    const handler = (event: KeyboardEvent) => {
      if (
        (event.metaKey || event.ctrlKey) &&
        event.key.toLowerCase() === 'k' &&
        !document.querySelector('dialog[open]')
      ) {
        event.preventDefault();
        setQuery('');
        dialog.current?.showModal();
        input.current?.focus();
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);
  return (
    <>
      <button
        type="button"
        className="command-trigger"
        aria-label={t('Quick navigation')}
        title={t('Quick navigation')}
        onClick={show}
      >
        <Icon name="search" />
        <span>{t('Jump to…')}</span>
        <kbd>⌘ K</kbd>
      </button>
      <dialog
        ref={dialog}
        className="command-dialog"
        aria-label={t('Quick navigation')}
        onClick={(e) => {
          if (e.target === dialog.current) dialog.current?.close();
        }}
        onKeyDown={(e) => {
          if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
            e.preventDefault();
            const choices = Array.from(
              dialog.current?.querySelectorAll<HTMLButtonElement>(
                '[data-command]'
              ) ?? []
            );
            if (!choices.length) return;
            const current = choices.indexOf(
              document.activeElement as HTMLButtonElement
            );
            const next =
              current < 0
                ? e.key === 'ArrowDown'
                  ? 0
                  : choices.length - 1
                : (current + (e.key === 'ArrowDown' ? 1 : choices.length - 1)) %
                  choices.length;
            choices[next]?.focus();
          }
        }}
      >
        <div className="command-search">
          <Icon name="search" />
          <input
            ref={input}
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && results[0]) {
                dialog.current?.close();
                navigate(results[0][2]);
              }
            }}
            name="navigation-search"
            autoComplete="off"
            aria-label={t('Search pages')}
            placeholder={t('Where would you like to go?')}
          />
          <button
            className="command-close"
            onClick={() => dialog.current?.close()}
            aria-label={t('Close quick navigation')}
          >
            Esc
          </button>
        </div>
        <p className="command-label">{t('PAGES & ACTIONS')}</p>
        <ul>
          {results.map(([en, es, to, icon]) => (
            <li key={to}>
              <button
                data-command
                type="button"
                onClick={() => {
                  dialog.current?.close();
                  navigate(to);
                }}
              >
                <Icon name={icon} />
                <span>{c(en, es)}</span>
                <span aria-hidden="true">↗</span>
              </button>
            </li>
          ))}
        </ul>
        {!results.length && (
          <p className="command-empty" role="status">
            {t('No pages match your search.')}
          </p>
        )}
        <div className="command-hint">
          <span>↑ ↓ {t('to navigate')}</span>
          <span>↵ {t('to open')}</span>
        </div>
      </dialog>
    </>
  );
}
