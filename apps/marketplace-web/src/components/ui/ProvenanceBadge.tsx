import { useState, useId } from 'react';
import {
  type EconomicMetricMetadata,
  type DataProvenance,
  type ValidationStatus,
  getProvenanceVisuals,
  getStatusLabel,
  getStatusTone,
} from '../../app/provenance';
import { useI18n } from '../../app/i18n';

function ProvenanceIcon({
  name,
}: {
  name: 'check' | 'shield' | 'spark' | 'alert' | 'clock';
}) {
  return (
    <svg
      width="13"
      height="13"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {name === 'check' && <path d="m5 12 5 5 9-10" />}
      {name === 'shield' && (
        <>
          <path d="M12 3 4 6v6c0 5 3.5 8 8 9 4.5-1 8-4 8-9V6Z" />
          <path d="m9 12 2 2 4-4" />
        </>
      )}
      {name === 'spark' && (
        <path d="M12 3v4m0 10v4M3 12h4m10 0h4M6 6l2.5 2.5m7 7L18 18M6 18l2.5-2.5m7-7L18 6" />
      )}
      {name === 'alert' && (
        <>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 8v4M12 16h.01" />
        </>
      )}
      {name === 'clock' && (
        <>
          <circle cx="12" cy="12" r="9" />
          <path d="M12 7v5l3 2" />
        </>
      )}
    </svg>
  );
}

export interface ProvenanceBadgeProps {
  meta?: EconomicMetricMetadata;
  provenance?: DataProvenance;
  status?: ValidationStatus;
  source?: string;
  network?: string;
  period?: string;
  compact?: boolean;
  className?: string;
}

export function ProvenanceBadge({
  meta,
  provenance = meta?.provenance ?? 'SIMULATED',
  status = meta?.status ?? 'SIMULATED_PROJECTION',
  source = meta?.source ?? 'Deterministic Simulation Model',
  network = meta?.network ?? 'Simulated Environment',
  period = meta?.period ?? '30-day Window',
  compact = false,
  className = '',
}: ProvenanceBadgeProps) {
  const { locale } = useI18n();
  const [open, setOpen] = useState(false);
  const popoverId = useId();

  const isEs = locale === 'es';
  const visuals = getProvenanceVisuals(provenance, isEs ? 'es' : 'en', status);
  const statusLabel = getStatusLabel(status, isEs ? 'es' : 'en');
  const statusTone = getStatusTone(status);

  return (
    <span
      className={`provenance-badge-wrap ${className}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
      onFocus={() => setOpen(true)}
      onBlur={() => setOpen(false)}
    >
      <button
        type="button"
        className={`provenance-badge ${visuals.badgeClass} ${compact ? 'compact' : ''}`}
        aria-describedby={open ? popoverId : undefined}
        aria-label={`${visuals.label} · ${statusLabel}`}
        onClick={(e) => {
          e.preventDefault();
          setOpen((prev) => !prev);
        }}
      >
        <ProvenanceIcon name={visuals.iconName} />
        <span className="provenance-badge-text">{visuals.label}</span>
      </button>

      {open && (
        <span
          id={popoverId}
          role="tooltip"
          className="provenance-popover"
          aria-live="polite"
        >
          <span className="popover-row popover-header">
            <strong>{visuals.label}</strong>
            <span className={`popover-status popover-status-${statusTone}`}>
              {statusLabel}
            </span>
          </span>

          <span className="popover-row">
            <span className="popover-key">{isEs ? 'Fuente:' : 'Source:'}</span>
            <span className="popover-val">{source}</span>
          </span>

          <span className="popover-row">
            <span className="popover-key">{isEs ? 'Red:' : 'Network:'}</span>
            <span className="popover-val">{network}</span>
          </span>

          <span className="popover-row">
            <span className="popover-key">{isEs ? 'Período:' : 'Period:'}</span>
            <span className="popover-val">{period}</span>
          </span>
        </span>
      )}
    </span>
  );
}
