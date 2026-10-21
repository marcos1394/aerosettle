/**
 * Data-visualisation primitives for Conatus. Pure SVG, no dependencies.
 * Styles live in styles/viz.css.
 */
import {
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type ReactNode,
} from 'react';
import type { Embodiment, Sustainability } from '../../app/atlas';
import { useI18n } from '../../app/i18n';

export type Tone = 'accent' | 'success' | 'warning' | 'error' | 'muted' | 'violet';
const TONE: Record<Tone, string> = {
  accent: 'var(--accent)',
  success: 'var(--success)',
  warning: 'var(--warning)',
  error: 'var(--error)',
  muted: 'var(--muted)',
  violet: '#9fb4ff',
};

const prefersReducedMotion = () =>
  typeof window !== 'undefined' &&
  window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Counts up to `value` once it scrolls into view. */
export function AnimatedNumber({
  value,
  format,
  duration = 1100,
}: {
  value: number;
  format: (value: number) => string;
  duration?: number;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const [shown, setShown] = useState(() => (prefersReducedMotion() ? value : 0));
  const from = useRef(0);
  useEffect(() => {
    if (prefersReducedMotion()) {
      setShown(value);
      return;
    }
    const node = ref.current;
    let frame = 0;
    let started = false;
    const run = () => {
      started = true;
      const start = performance.now();
      const origin = from.current;
      const tick = (now: number) => {
        const t = Math.min(1, (now - start) / duration);
        const eased = 1 - Math.pow(1 - t, 4);
        const next = origin + (value - origin) * eased;
        setShown(next);
        if (t < 1) frame = requestAnimationFrame(tick);
        else from.current = value;
      };
      frame = requestAnimationFrame(tick);
    };
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting && !started) run();
      },
      { threshold: 0.2 }
    );
    if (node) observer.observe(node);
    return () => {
      observer.disconnect();
      cancelAnimationFrame(frame);
    };
  }, [value, duration]);
  return (
    <span ref={ref} className="tabular">
      {format(shown)}
    </span>
  );
}

/** Minimal trend line. */
export function Sparkline({
  values,
  tone = 'accent',
  width = 120,
  height = 36,
  fill = true,
}: {
  values: number[];
  tone?: Tone;
  width?: number;
  height?: number;
  fill?: boolean;
}) {
  const id = useId();
  const { line, area } = useMemo(() => path(values, width, height, 3), [values, width, height]);
  return (
    <svg
      className="sparkline"
      viewBox={`0 0 ${width} ${height}`}
      width={width}
      height={height}
      aria-hidden="true"
      preserveAspectRatio="none"
    >
      <defs>
        <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor={TONE[tone]} stopOpacity="0.35" />
          <stop offset="1" stopColor={TONE[tone]} stopOpacity="0" />
        </linearGradient>
      </defs>
      {fill && <path d={area} fill={`url(#${id})`} />}
      <path d={line} fill="none" stroke={TONE[tone]} strokeWidth="1.6" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

function path(values: number[], width: number, height: number, pad = 0) {
  if (!values.length) return { line: '', area: '', points: [] as [number, number][] };
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const points = values.map((v, i): [number, number] => [
    (i / Math.max(1, values.length - 1)) * width,
    pad + (1 - (v - min) / span) * (height - pad * 2),
  ]);
  // Smooth with a light cardinal spline.
  let line = `M${points[0][0]},${points[0][1]}`;
  for (let i = 1; i < points.length; i++) {
    const [x0, y0] = points[i - 1];
    const [x1, y1] = points[i];
    const cx = (x0 + x1) / 2;
    line += ` C${cx},${y0} ${cx},${y1} ${x1},${y1}`;
  }
  const area = `${line} L${width},${height} L0,${height} Z`;
  return { line, area, points };
}

/** Interactive area chart with hover read-out. */
export function AreaChart({
  values,
  labels,
  format,
  tone = 'accent',
  height = 220,
  label,
}: {
  values: number[];
  labels: string[];
  format: (value: number) => string;
  tone?: Tone;
  height?: number;
  label: string;
}) {
  const id = useId();
  const width = 800;
  const { line, area, points } = useMemo(() => path(values, width, height, 18), [values, height]);
  const [hover, setHover] = useState<number | null>(null);
  const index = hover ?? values.length - 1;
  const point = points[index];
  const svg = useRef<SVGSVGElement>(null);
  function move(clientX: number) {
    const box = svg.current?.getBoundingClientRect();
    if (!box) return;
    const ratio = Math.min(1, Math.max(0, (clientX - box.left) / box.width));
    setHover(Math.round(ratio * (values.length - 1)));
  }
  return (
    <figure className="area-chart" aria-label={label}>
      <figcaption className="area-readout" aria-live="polite">
        <strong className="tabular">{format(values[index] ?? 0)}</strong>
        <span>{labels[index]}</span>
      </figcaption>
      <div className="area-plot">
      <svg
        style={{ height }}
        ref={svg}
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        role="img"
        aria-label={label}
        onPointerMove={(e) => move(e.clientX)}
        onPointerLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0" stopColor={TONE[tone]} stopOpacity="0.28" />
            <stop offset="1" stopColor={TONE[tone]} stopOpacity="0" />
          </linearGradient>
        </defs>
        {[0.25, 0.5, 0.75].map((y) => (
          <line key={y} x1="0" x2={width} y1={height * y} y2={height * y} className="grid-line" />
        ))}
        <path d={area} fill={`url(#${id})`} />
        <path d={line} fill="none" stroke={TONE[tone]} strokeWidth="2" vectorEffect="non-scaling-stroke" className="draw-line" />
        {point && (
          <g className="area-cursor">
            <line x1={point[0]} x2={point[0]} y1="0" y2={height} vectorEffect="non-scaling-stroke" />
          </g>
        )}
      </svg>
      {point && (
        <span
          className="area-dot"
          style={{ left: `${(point[0] / width) * 100}%`, top: `${(point[1] / height) * 100}%`, background: TONE[tone] }}
          aria-hidden="true"
        />
      )}
      </div>
      <div className="area-axis" aria-hidden="true">
        <span>{labels[0]}</span>
        <span>{labels[Math.floor(labels.length / 2)]}</span>
        <span>{labels[labels.length - 1]}</span>
      </div>
    </figure>
  );
}

/** Donut chart with legend. */
export function Donut({
  segments,
  size = 156,
  center,
}: {
  segments: { label: string; value: number; tone: Tone | string }[];
  size?: number;
  center?: ReactNode;
}) {
  const total = segments.reduce((a, s) => a + s.value, 0) || 1;
  const radius = 42;
  const circumference = 2 * Math.PI * radius;
  let offset = 0;
  return (
    <div className="donut" style={{ '--size': `${size}px` } as CSSProperties}>
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle cx="50" cy="50" r={radius} className="donut-track" />
        {segments.map((segment) => {
          const length = (segment.value / total) * circumference;
          const node = (
            <circle
              key={segment.label}
              cx="50"
              cy="50"
              r={radius}
              stroke={TONE[segment.tone as Tone] ?? segment.tone}
              strokeDasharray={`${Math.max(0, length - 1.2)} ${circumference}`}
              strokeDashoffset={-offset}
              className="donut-segment"
            />
          );
          offset += length;
          return node;
        })}
      </svg>
      {center && <div className="donut-center">{center}</div>}
    </div>
  );
}

/** Ring gauge (0–1). */
export function Ring({
  value,
  tone = 'accent',
  size = 120,
  children,
  label,
}: {
  value: number;
  tone?: Tone;
  size?: number;
  children?: ReactNode;
  label: string;
}) {
  const radius = 44;
  const circumference = 2 * Math.PI * radius;
  const clamped = Math.min(1, Math.max(0, value));
  return (
    <div
      className="ring"
      style={{ '--size': `${size}px` } as CSSProperties}
      role="meter"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped * 100)}
    >
      <svg viewBox="0 0 100 100" aria-hidden="true">
        <circle cx="50" cy="50" r={radius} className="ring-track" />
        <circle
          cx="50"
          cy="50"
          r={radius}
          className="ring-value"
          stroke={TONE[tone]}
          strokeDasharray={`${clamped * circumference} ${circumference}`}
        />
      </svg>
      <div className="ring-center">{children}</div>
    </div>
  );
}

/** Horizontal meter bar (0–1). */
export function Meter({ value, tone = 'accent', label }: { value: number; tone?: Tone; label?: string }) {
  return (
    <span
      className="meter"
      role={label ? 'meter' : undefined}
      aria-label={label}
      aria-valuemin={label ? 0 : undefined}
      aria-valuemax={label ? 100 : undefined}
      aria-valuenow={label ? Math.round(Math.min(1, value) * 100) : undefined}
    >
      <span style={{ width: `${Math.min(1, Math.max(0, value)) * 100}%`, background: TONE[tone] }} />
    </span>
  );
}

/** Ranked horizontal bars. */
export function BarList({
  items,
  format,
  tone = 'accent',
}: {
  items: { label: ReactNode; value: number; key: string; hint?: ReactNode }[];
  format: (value: number) => string;
  tone?: Tone;
}) {
  const max = Math.max(...items.map((i) => i.value), 1);
  return (
    <ul className="bar-list">
      {items.map((item) => (
        <li key={item.key}>
          <div className="bar-list-label">
            <span>{item.label}</span>
            <strong className="tabular">{format(item.value)}</strong>
          </div>
          <Meter value={item.value / max} tone={tone} />
          {item.hint && <small>{item.hint}</small>}
        </li>
      ))}
    </ul>
  );
}

/** Small vertical bar chart. */
export function Bars({ values, tone = 'accent', height = 64 }: { values: number[]; tone?: Tone; height?: number }) {
  const max = Math.max(...values.map(Math.abs), 1);
  return (
    <div className="bars" style={{ height }} aria-hidden="true">
      {values.map((value, i) => (
        <span
          key={i}
          style={{
            height: `${Math.max(4, (Math.abs(value) / max) * 100)}%`,
            background: value < 0 ? TONE.error : TONE[tone],
            animationDelay: `${i * 18}ms`,
          }}
        />
      ))}
    </div>
  );
}

// ───────────────────────────── Glyphs ─────────────────────────────

const EMBODIMENT_PATHS: Record<Embodiment, ReactNode> = {
  Drone: (
    <>
      <circle cx="6" cy="6" r="2.6" />
      <circle cx="18" cy="6" r="2.6" />
      <circle cx="6" cy="18" r="2.6" />
      <circle cx="18" cy="18" r="2.6" />
      <path d="M8 8l2.5 2.5M16 8l-2.5 2.5M8 16l2.5-2.5M16 16l-2.5-2.5" />
      <rect x="10" y="10" width="4" height="4" rx="1" />
    </>
  ),
  Ugv: (
    <>
      <rect x="4" y="8" width="16" height="7" rx="2" />
      <circle cx="7.5" cy="17.5" r="2" />
      <circle cx="16.5" cy="17.5" r="2" />
      <path d="M9 8V5h5l2 3" />
    </>
  ),
  Amr: (
    <>
      <rect x="5" y="5" width="14" height="12" rx="3" />
      <circle cx="9.5" cy="10" r="1" />
      <circle cx="14.5" cy="10" r="1" />
      <path d="M8 19h8M12 2v3" />
    </>
  ),
  RobotArm: (
    <>
      <path d="M5 20h9M9 20v-4l5-6 4 3" />
      <circle cx="9" cy="16" r="1.4" />
      <circle cx="14" cy="10" r="1.4" />
      <path d="M18 13l2-2m-2 2 1 3" />
    </>
  ),
  Camera: (
    <>
      <rect x="3" y="8" width="13" height="9" rx="2" />
      <path d="m16 11 5-3v9l-5-3" />
      <circle cx="9.5" cy="12.5" r="2" />
    </>
  ),
  IotSensor: (
    <>
      <rect x="9" y="11" width="6" height="9" rx="1.5" />
      <path d="M7 8a7 7 0 0 1 10 0M4.5 5.5a10.5 10.5 0 0 1 15 0" />
      <circle cx="12" cy="14" r="1" />
    </>
  ),
  Vehicle: (
    <>
      <path d="M3 15v-3l2-5h11l3 5h2v3" />
      <circle cx="7" cy="16.5" r="2" />
      <circle cx="17" cy="16.5" r="2" />
      <path d="M6 11h13" />
    </>
  ),
  IndustrialMachine: (
    <>
      <path d="M3 20V10l5 3V10l5 3V6h5v14Z" />
      <path d="M7 17h2m3 0h2m3 0h0" />
    </>
  ),
  EdgeCompute: (
    <>
      <rect x="6" y="6" width="12" height="12" rx="2" />
      <rect x="9.5" y="9.5" width="5" height="5" rx="1" />
      <path d="M9 3v3m6-3v3M9 18v3m6-3v3M3 9h3m-3 6h3m12-6h3m-3 6h3" />
    </>
  ),
  EnergyAsset: <path d="M13 2 5 13h6l-1 9 8-11h-6Z" />,
};

export function EmbodimentGlyph({
  embodiment,
  size = 44,
  tone,
}: {
  embodiment: string;
  size?: number;
  tone?: Sustainability;
}) {
  const paths = EMBODIMENT_PATHS[embodiment as Embodiment] ?? EMBODIMENT_PATHS.EdgeCompute;
  return (
    <span
      className={`glyph ${tone ? `glyph-${tone}` : ''}`}
      style={{ '--size': `${size}px` } as CSSProperties}
      aria-hidden="true"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round">
        {paths}
      </svg>
    </span>
  );
}

/** Generative identicon from an address/seed, used as an on-chain avatar. */
export function Identicon({ seed, size = 28 }: { seed: string; size?: number }) {
  const cells = useMemo(() => {
    let h = 2166136261;
    for (const ch of seed) h = Math.imul(h ^ ch.charCodeAt(0), 16777619);
    const bits: boolean[] = [];
    for (let i = 0; i < 15; i++) bits.push(((h >>> i) & 1) === 1);
    const hue = Math.abs(h) % 360;
    return { bits, hue };
  }, [seed]);
  return (
    <svg className="identicon" viewBox="0 0 5 5" width={size} height={size} aria-hidden="true" shapeRendering="crispEdges">
      <rect width="5" height="5" fill={`hsl(${cells.hue} 30% 14%)`} />
      {cells.bits.map((on, i) => {
        if (!on) return null;
        const x = Math.floor(i / 5);
        const y = i % 5;
        return (
          <g key={i} fill={`hsl(${cells.hue} 70% 68%)`}>
            <rect x={x} y={y} width="1" height="1" />
            <rect x={4 - x} y={y} width="1" height="1" />
          </g>
        );
      })}
    </svg>
  );
}

/** Live pulse dot. */
export function Pulse({ tone = 'success' }: { tone?: Tone }) {
  return <span className="pulse" style={{ '--tone': TONE[tone] } as CSSProperties} aria-hidden="true" />;
}

/** Marks a capability whose on-chain module is still rolling out. */
export function EarlyAccess({ label }: { label?: string }) {
  const { locale } = useI18n();
  return (
    <span className="early-access" title={locale === 'es' ? 'Disponible en acceso anticipado' : 'Available in early access'}>
      {label ?? (locale === 'es' ? 'Acceso anticipado' : 'Early access')}
    </span>
  );
}

/** Sustainability label + tone. */
export function SustainabilityBadge({ value }: { value: Sustainability }) {
  const { locale } = useI18n();
  const copy: Record<Sustainability, [string, string]> = {
    thriving: ['Thriving', 'Prosperando'],
    stable: ['Self-sustaining', 'Autosostenible'],
    'at-risk': ['Needs work', 'Necesita trabajo'],
  };
  return (
    <span className={`sustain sustain-${value}`}>
      <span aria-hidden="true" />
      {copy[value][locale === 'es' ? 1 : 0]}
    </span>
  );
}

export const sustainabilityTone = (value: Sustainability): Tone =>
  value === 'thriving' ? 'accent' : value === 'stable' ? 'success' : 'warning';

/** Stylised world map with plotted points. Positions are 0–100 (see atlas.project). */
export function WorldMap({
  points,
  label,
}: {
  points: { key: string; position: [number, number]; tone?: Tone; size?: number; title?: string; active?: boolean }[];
  label: string;
}) {
  // A dotted continent silhouette sampled from coarse geographic boxes.
  return (
    <div className="world-map" role="img" aria-label={label}>
      <svg viewBox="0 1 100 41" preserveAspectRatio="xMidYMid meet" aria-hidden="true">
        {LAND_DOTS.map(([x, y]) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r="0.42" className="land-dot" />
        ))}
        {points.map((point) => (
          <g key={point.key} transform={`translate(${point.position[0]} ${point.position[1] / 2})`}>
            {point.active && <circle r="2.6" className="map-ping" style={{ fill: TONE[point.tone ?? 'accent'] }} />}
            <circle r={point.size ?? 0.9} style={{ fill: TONE[point.tone ?? 'accent'] }}>
              {point.title && <title>{point.title}</title>}
            </circle>
          </g>
        ))}
      </svg>
    </div>
  );
}

/** Coarse continental boxes: [lonMin, lonMax, latMin, latMax]. */
const LAND_BOXES: [number, number, number, number][] = [
  // North America
  [-168, -140, 55, 71], [-140, -60, 50, 72], [-125, -68, 30, 50], [-82, -78, 25, 31],
  [-117, -97, 17, 30], [-97, -83, 14, 22], [-90, -77, 7, 15], [-55, -20, 60, 82],
  [-95, -75, 62, 72],
  // South America
  [-80, -35, -5, 11], [-75, -38, -20, -5], [-72, -48, -35, -20], [-74, -64, -54, -35],
  // Europe
  [-10, 30, 36, 60], [5, 32, 55, 70], [-8, 2, 50, 58], [-24, -14, 63, 66],
  // Africa
  [-17, 35, 5, 35], [10, 42, -34, 5], [35, 51, 0, 12], [43, 50, -25, -13],
  // Asia
  [30, 180, 50, 74], [40, 140, 25, 50], [35, 60, 13, 30], [68, 90, 8, 25],
  [95, 122, 2, 25], [98, 140, -8, 2], [130, 145, 31, 45], [120, 125, 10, 20],
  // Oceania
  [113, 153, -38, -12], [141, 150, -9, -3], [166, 178, -46, -35],
];
const LAND_DOTS: [number, number][] = (() => {
  const dots: [number, number][] = [];
  for (let lat = 85; lat > -60; lat -= 4.5)
    for (let lon = -178; lon < 180; lon += 4.5)
      if (LAND_BOXES.some(([a, b, c, d]) => lon >= a && lon <= b && lat >= c && lat <= d))
        dots.push([((lon + 180) / 360) * 100, ((90 - lat) / 180) * 50]);
  return dots;
})();
