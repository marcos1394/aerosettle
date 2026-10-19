import { useRef, useState } from 'react';
import { Link } from 'react-router';
import { useCopy, useI18n } from '../../app/i18n';
import { PageHeader } from '../../components/ui';
import '../../styles/planner.css';

const families = [
  {
    id: 'inspect',
    en: 'Inspect',
    es: 'Inspeccionar',
    glyph: '◎',
    enDetail: 'Assess an asset or a site.',
    esDetail: 'Evaluar un activo o un sitio.',
    enProof: 'A coverage report with annotated observations.',
    esProof: 'Un reporte de cobertura con observaciones anotadas.',
    enObjective:
      'Perform a radiometric thermal sweep across 48 MW of solar strings and flag cells exceeding +12 °C delta.',
    esObjective:
      'Ejecutar un barrido térmico radiométrico sobre 48 MW de paneles solares y señalar celdas con delta superior a +12 °C.',
    enAcceptance:
      '100% string coverage with RTK geotags (<3 cm RMSE) verified by the site engineering lead.',
    esAcceptance:
      'Cobertura del 100% de cadenas con geoetiquetas RTK (<3 cm RMSE) aprobada por el responsable de ingeniería.',
    enStop:
      'Pause flight and return to home if wind gusts exceed 11 m/s or precipitation begins.',
    esStop:
      'Pausar el vuelo y regresar a base si las ráfagas superan 11 m/s o inicia precipitación.',
  },
  {
    id: 'deliver',
    en: 'Deliver',
    es: 'Entregar',
    glyph: '↗',
    enDetail: 'Move something to its destination.',
    esDetail: 'Mover algo a su destino.',
    enProof: 'Pickup and handoff records with recipient acceptance.',
    esProof: 'Registros de recolección y entrega con aceptación del receptor.',
    enObjective:
      'Transport 40 cold-chain biologic vials from the central depot to three clinics while maintaining 2–8 °C.',
    esObjective:
      'Transportar 40 viales biológicos en cadena de frío desde el depósito central a tres clínicas manteniendo 2–8 °C.',
    enAcceptance:
      'Continuous temperature log within 2–8 °C and cryptographic handoff signature at each clinic.',
    esAcceptance:
      'Registro continuo de temperatura entre 2–8 °C y firma criptográfica de recepción en cada clínica.',
    enStop:
      'Abort route and alert dispatch if internal payload chamber exceeds 7.2 °C for more than 90 seconds.',
    esStop:
      'Abortar ruta y alertar a despacho si la cámara interna supera 7.2 °C durante más de 90 segundos.',
  },
  {
    id: 'manipulate',
    en: 'Manipulate',
    es: 'Manipular',
    glyph: '⌘',
    enDetail: 'Transform or assemble a physical object.',
    esDetail: 'Transformar o ensamblar un objeto físico.',
    enProof: 'Before-and-after records and a measured quality check.',
    esProof:
      'Registros de antes y después y una verificación medible de calidad.',
    enObjective:
      'Machine and deburr 500 aluminium mounting brackets to ISO 2768-f tolerances with automated CMM probing.',
    esObjective:
      'Maquinar y desbarbar 500 soportes de aluminio bajo tolerancias ISO 2768-f con inspección CMM automatizada.',
    enAcceptance:
      'Zero critical dimensional deviations across sampled lot and signed spindle/CMM telemetry archive.',
    esAcceptance:
      'Cero desviaciones dimensionales críticas en el lote muestreado y archivo de telemetría CMM firmado.',
    enStop:
      'Halt cell immediately if tool wear torque exceeds 115% nominal threshold or vision QA flags burr defects.',
    esStop:
      'Detener la celda de inmediato si el par de desgaste supera el 115% nominal o visión QA detecta rebabas.',
  },
  {
    id: 'observe',
    en: 'Observe',
    es: 'Observar',
    glyph: '◉',
    enDetail: 'Capture a defined signal over time.',
    esDetail: 'Capturar una señal durante un periodo.',
    enProof: 'Timestamped readings with calibration and coverage notes.',
    esProof: 'Lecturas con fecha, notas de calibración y cobertura.',
    enObjective:
      'Record hourly PM2.5, NO₂, and acoustic levels across 12 port perimeter nodes for 72 consecutive hours.',
    esObjective:
      'Registrar lecturas horarias de PM2.5, NO₂ y niveles acústicos en 12 nodos perimetrales durante 72 horas.',
    enAcceptance:
      'At least 99% interval completeness with zero-drift calibration attestation signed by each sensor node.',
    esAcceptance:
      'Al menos 99% de completitud de intervalos con atestación de calibración firmada por cada nodo sensor.',
    enStop:
      'Flag node and request field maintenance if sensor zero-point drift exceeds 3% or battery drops below 15%.',
    esStop:
      'Marcar nodo y solicitar mantenimiento si la deriva supera el 3% o la batería baja del 15%.',
  },
];

export default function MissionPlanner() {
  const { locale } = useI18n();
  const c = useCopy();
  const [step, setStep] = useState(0);
  const [family, setFamily] = useState('inspect');
  const [objective, setObjective] = useState('');
  const [evidence, setEvidence] = useState('');
  const [acceptance, setAcceptance] = useState('');
  const [stop, setStop] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');
  const heading = useRef<HTMLHeadingElement>(null);
  const selected = families.find((f) => f.id === family)!;
  const labels = [
    c('Define the work', 'Definir el trabajo'),
    c('Set the conditions', 'Establecer condiciones'),
    c('Review & export', 'Revisar y exportar'),
  ];
  const complete = [objective, evidence, acceptance, stop].filter(
    (v) => v.trim().length >= 10
  ).length;
  const canReview = complete === 4;

  function loadTemplate() {
    setObjective(locale === 'es' ? selected.esObjective : selected.enObjective);
    setEvidence(locale === 'es' ? selected.esProof : selected.enProof);
    setAcceptance(
      locale === 'es' ? selected.esAcceptance : selected.enAcceptance
    );
    setStop(locale === 'es' ? selected.esStop : selected.enStop);
    setError('');
    setNotice(
      c(
        'Template loaded. Customize any field or proceed to review.',
        'Plantilla cargada. Personaliza cualquier campo o avanza a la revisión.'
      )
    );
  }

  function go(next: number) {
    setError('');
    setNotice('');
    if (next > 0 && objective.trim().length < 10) {
      setError(
        c(
          'Describe the intended outcome in at least 10 characters.',
          'Describe el resultado esperado con al menos 10 caracteres.'
        )
      );
      return;
    }
    if (next === 2 && !canReview) {
      setError(
        c(
          'Add at least 10 characters for evidence, acceptance and stop conditions.',
          'Agrega al menos 10 caracteres para evidencia, aceptación y condiciones de parada.'
        )
      );
      return;
    }
    setStep(next);
    requestAnimationFrame(() => heading.current?.focus());
  }
  function download() {
    if (!canReview) return;
    const brief = {
      schema: 'conatus.mission-brief.v1',
      status: 'ready-for-contracting',
      createdAt: new Date().toISOString(),
      language: locale,
      workFamily: family,
      objective: objective.trim(),
      evidence: evidence.trim(),
      acceptanceCriteria: acceptance.trim(),
      stopConditions: stop.trim(),
      execution: {
        published: false,
        agentReserved: false,
        paymentAuthorized: false,
      },
    };
    const url = URL.createObjectURL(
      new Blob([JSON.stringify(brief, null, 2)], { type: 'application/json' })
    );
    const a = document.createElement('a');
    a.href = url;
    a.download = 'conatus-mission-brief.json';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
    setNotice(
      c(
        'Brief exported. Ready to attach to your on-chain work order.',
        'Encargo exportado. Listo para vincularse a tu orden de trabajo on-chain.'
      )
    );
  }
  return (
    <div className="planner-page">
      <PageHeader
        eyebrow={c(
          'MISSION ARCHITECTURE · SOLANA',
          'ARQUITECTURA DE MISIÓN · SOLANA'
        )}
        title={c('Mission planner', 'Planificador de misiones')}
        description={c(
          'Turn physical operations into a verifiable, machine-readable specification with explicit evidence and safety boundaries.',
          'Convierte operaciones físicas en una especificación verificable con requisitos explícitos de evidencia y límites de seguridad.'
        )}
        action={
          <button type="button" className="button" onClick={loadTemplate}>
            {c('Load sample specification', 'Cargar especificación de ejemplo')}
          </button>
        }
      />
      <div className="planner-layout">
        <div className="planner-work">
          <nav
            className="planner-steps"
            aria-label={c('Planning steps', 'Pasos de planificación')}
          >
            {labels.map((label, i) => (
              <button
                key={i}
                aria-current={step === i ? 'step' : undefined}
                onClick={() => go(i)}
                disabled={
                  i > step &&
                  (i === 1 ? objective.trim().length < 10 : !canReview)
                }
              >
                <span>{i + 1}</span>
                {label}
              </button>
            ))}
          </nav>
          <h2 ref={heading} tabIndex={-1}>
            {labels[step]}
          </h2>
          {step === 0 && (
            <div className="planner-fields">
              <fieldset className="family-fieldset">
                <legend>
                  {c('What kind of work?', '¿Qué tipo de trabajo?')}
                </legend>
                <div className="family-grid">
                  {families.map((f) => (
                    <label
                      key={f.id}
                      className={family === f.id ? 'selected' : ''}
                    >
                      <input
                        type="radio"
                        name="work-family"
                        value={f.id}
                        checked={family === f.id}
                        onChange={() => setFamily(f.id)}
                      />
                      <span className="family-symbol" aria-hidden="true">
                        {f.glyph}
                      </span>
                      <strong>{locale === 'es' ? f.es : f.en}</strong>
                      <small>{locale === 'es' ? f.esDetail : f.enDetail}</small>
                    </label>
                  ))}
                </div>
              </fieldset>
              <label htmlFor="brief-objective">
                {c('Intended outcome', 'Resultado esperado')}
              </label>
              <textarea
                id="brief-objective"
                value={objective}
                onChange={(e) => setObjective(e.target.value)}
                rows={4}
                maxLength={1200}
                placeholder={c(
                  'Describe the result someone should be able to accept…',
                  'Describe el resultado que alguien debería poder aceptar…'
                )}
                aria-describedby="objective-help"
              />
              <small id="objective-help">
                {c(
                  'Use a measurable outcome. Keep personal information and precise sensitive locations out of the public manifest.',
                  'Usa un resultado medible. Evita información personal y ubicaciones sensibles precisas en el manifiesto público.'
                )}
              </small>
              <button className="button primary" onClick={() => go(1)}>
                {c('Define acceptance', 'Definir aceptación')} →
              </button>
            </div>
          )}
          {step === 1 && (
            <div className="planner-fields">
              <label htmlFor="brief-evidence">
                {c('Required evidence', 'Evidencia requerida')}
              </label>
              <textarea
                id="brief-evidence"
                value={evidence}
                onChange={(e) => setEvidence(e.target.value)}
                maxLength={1200}
                rows={3}
              />
              <div className="planner-suggestion">
                <small>
                  {c(
                    'Starting point for your brief',
                    'Punto de partida para tu encargo'
                  )}
                </small>
                <p>{locale === 'es' ? selected.esProof : selected.enProof}</p>
                <button
                  onClick={() =>
                    setEvidence(
                      locale === 'es' ? selected.esProof : selected.enProof
                    )
                  }
                >
                  {c('Use this suggestion', 'Usar esta sugerencia')}
                </button>
              </div>
              <label htmlFor="brief-acceptance">
                {c(
                  'Acceptance rule & reviewer',
                  'Regla de aceptación y revisor'
                )}
              </label>
              <textarea
                id="brief-acceptance"
                value={acceptance}
                onChange={(e) => setAcceptance(e.target.value)}
                maxLength={1200}
                rows={3}
                placeholder={c(
                  'What must pass, and which role can approve it?',
                  '¿Qué debe cumplirse y qué rol puede aprobarlo?'
                )}
              />
              <label htmlFor="brief-stop">
                {c('Stop conditions', 'Condiciones de parada')}
              </label>
              <textarea
                id="brief-stop"
                value={stop}
                onChange={(e) => setStop(e.target.value)}
                maxLength={1200}
                rows={3}
                placeholder={c(
                  'When should the operator pause and request a review?',
                  '¿Cuándo debe el operador detenerse y pedir una revisión?'
                )}
              />
              <div className="planner-buttons">
                <button className="button" onClick={() => go(0)}>
                  {c('Back', 'Volver')}
                </button>
                <button className="button primary" onClick={() => go(2)}>
                  {c('Review brief', 'Revisar encargo')} →
                </button>
              </div>
            </div>
          )}
          {step === 2 && (
            <div className="planner-review">
              <span className="planner-local">
                {c(
                  'MISSION SPECIFICATION · READY FOR SOLANA',
                  'ESPECIFICACIÓN DE MISIÓN · LISTA PARA SOLANA'
                )}
              </span>
              <dl>
                {[
                  [
                    c('Work family', 'Tipo de trabajo'),
                    locale === 'es' ? selected.es : selected.en,
                  ],
                  [c('Objective', 'Objetivo'), objective],
                  [c('Evidence', 'Evidencia'), evidence],
                  [c('Acceptance', 'Aceptación'), acceptance],
                  [c('Stop conditions', 'Condiciones de parada'), stop],
                ].map(([label, value]) => (
                  <div key={label}>
                    <dt>{label}</dt>
                    <dd>{value}</dd>
                  </div>
                ))}
              </dl>
              <div className="planner-buttons">
                <button className="button" onClick={() => go(1)}>
                  {c('Edit conditions', 'Editar condiciones')}
                </button>
                <button className="button primary" onClick={download}>
                  {c('Export JSON brief', 'Exportar encargo JSON')} ↓
                </button>
              </div>
              <div className="planner-next">
                <h3>
                  {c(
                    'Ready to publish on-chain?',
                    '¿Listo para publicar on-chain?'
                  )}
                </h3>
                <p>
                  {c(
                    'Commit your specification to an on-chain work order on Solana, lock the reward in USDC escrow, and open the mission to compatible autonomous machines.',
                    'Compromete tu especificación en una orden de trabajo on-chain en Solana, deposita la recompensa en custodia USDC y abre la misión a máquinas autónomas compatibles.'
                  )}
                </p>
                <Link to="/app/missions/new">
                  {c(
                    'Continue to on-chain publication',
                    'Continuar a la publicación on-chain'
                  )}{' '}
                  ↗
                </Link>
              </div>
            </div>
          )}
          {error && (
            <p role="alert" className="planner-error">
              {error}
            </p>
          )}
          <p role="status" className="planner-notice">
            {notice}
          </p>
        </div>
        <aside className="brief-sidebar">
          <span className="c-index">
            {c('MISSION BLUEPRINT', 'ESQUEMA DE MISIÓN')}
          </span>
          <div className="blueprint-symbol" aria-hidden="true">
            <span>{selected.glyph}</span>
          </div>
          <h2>{locale === 'es' ? selected.es : selected.en}</h2>
          <p>
            {c('Clarity before commitment.', 'Claridad antes del compromiso.')}
          </p>
          <div className="brief-progress">
            <span>
              {complete}/4 {c('fields prepared', 'campos preparados')}
            </span>
            <progress
              max={4}
              value={complete}
              aria-label={c('Brief completeness', 'Completitud del encargo')}
            />
          </div>
          <ul>
            {[
              [objective, c('Outcome', 'Resultado')],
              [evidence, c('Evidence', 'Evidencia')],
              [acceptance, c('Acceptance', 'Aceptación')],
              [stop, c('Stop conditions', 'Condiciones de parada')],
            ].map(([value, label]) => (
              <li key={label}>
                <span aria-hidden="true">
                  {value.trim().length >= 10 ? '✓' : '○'}
                </span>
                {label}
              </li>
            ))}
          </ul>
          <p className="brief-privacy">
            {c(
              'Drafting happens locally in your browser until you export the JSON manifest or publish the work order on Solana.',
              'La redacción ocurre localmente en tu navegador hasta que exportes el manifiesto JSON o publiques la orden en Solana.'
            )}
          </p>
          <Link to="/journal/evidence-before-settlement">
            {c('How to define useful evidence', 'Cómo definir evidencia útil')}{' '}
            ↗
          </Link>
        </aside>
      </div>
    </div>
  );
}
