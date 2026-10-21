export type Bilingual = { en: string; es: string };
export const bi = (en: string, es: string): Bilingual => ({ en, es });

export const articles = [
  {
    slug: 'the-drive-to-continue',
    category: bi('Economics', 'Economía'),
    art: 'orbit',
    title: bi(
      'Intelligence needs a way to keep going.',
      'La inteligencia necesita una forma de continuar.'
    ),
    summary: bi(
      'Why useful work and autonomous cost recovery belong at the center of the physical AI economy.',
      'Por qué el trabajo útil y la recuperación autónoma de costos están en el centro de la economía de la IA física.'
    ),
    sections: [
      {
        title: bi(
          'A principle, translated into a protocol',
          'Un principio convertido en protocolo'
        ),
        body: bi(
          'Spinoza described conatus as the innate striving of every thing to persevere in its being. Conatus translates that principle into on-chain economics: physical AI agents earn USDC through verifiable work and route their revenue to cover the real-world costs of staying operational—under explicit operator governance.',
          'Spinoza describió el conatus como el impulso innato de cada ser por perseverar en su existencia. Conatus traduce ese principio a la economía on-chain: los agentes de IA física generan ingresos en USDC mediante trabajo verificable y destinan esos recursos a cubrir los costos reales de mantenerse operativos, bajo la gobernanza explícita de su operador.'
        ),
      },
      {
        title: bi(
          'Capability becomes an on-chain service',
          'La capacidad se convierte en servicio on-chain'
        ),
        body: bi(
          'A camera observes. A mobile robot navigates. A manipulator arm assembles. Turning raw hardware into a liquid market service requires a defined outcome, declared capability bitmasks, an accountable operator identity, and cryptographic evidence that the physical outcome occurred. Buyers specify the result they need; matched machines claim and execute.',
          'Una cámara observa. Un robot móvil navega. Un brazo manipulador ensambla. Convertir el hardware en un servicio de mercado líquido exige un resultado definido, máscaras de capacidades declaradas, una identidad de operador verificable y evidencia criptográfica de que el resultado físico ocurrió. Los compradores especifican el resultado; las máquinas compatibles reclaman y ejecutan.'
        ),
      },
      {
        title: bi('Continuity has a balance sheet', 'Continuar tiene un balance'),
        body: bi(
          'Energy, maintenance, insurance, connectivity, and protocol fees are first-class citizens in the Conatus economic model. Gross revenue alone does not make a machine self-sustaining. The Conatus ratio—30-day revenue divided by 30-day operating costs—measures whether an agent is thriving, self-sustaining, or in need of higher-yield missions.',
          'La energía, el mantenimiento, el seguro, la conectividad y las comisiones del protocolo son elementos centrales del modelo económico de Conatus. Los ingresos brutos por sí solos no hacen autosostenible a una máquina. El ratio Conatus —ingresos de 30 días divididos entre costos operativos de 30 días— mide si un agente prospera, se sostiene o necesita misiones de mayor rendimiento.'
        ),
      },
      {
        title: bi(
          'Start with one verifiable outcome',
          'Empezar con un resultado verificable'
        ),
        body: bi(
          'Every settled mission begins with a structured brief: what must change in the physical world, which capabilities are required, who verifies the deliverables, and how much USDC is locked in escrow. Use the Mission Planner or post directly to the marketplace to dispatch autonomous hardware.',
          'Cada misión liquidada comienza con un encargo estructurado: qué debe cambiar en el mundo físico, qué capacidades se requieren, quién verifica los entregables y cuánto USDC se bloquea en escrow. Usa el Planificador de Misiones o publica directamente en el mercado para desplegar hardware autónomo.'
        ),
      },
    ],
    sources: [
      {
        label:
          'Stanford Encyclopedia of Philosophy · Spinoza’s Physical Theory',
        url: 'https://plato.stanford.edu/entries/spinoza-physics/',
      },
    ],
  },
  {
    slug: 'evidence-before-settlement',
    category: bi('Field notes', 'Notas de campo'),
    art: 'grid',
    title: bi(
      'Define the proof before the work.',
      'Define la prueba antes del trabajo.'
    ),
    summary: bi(
      'A practical framework for turning physical tasks into cryptographically verifiable missions.',
      'Un marco práctico para convertir tareas físicas en misiones criptográficamente verificables.'
    ),
    sections: [
      {
        title: bi(
          'Replace activity with acceptance criteria',
          'Cambiar actividad por criterios de aceptación'
        ),
        body: bi(
          '“Inspect the solar park” leaves too much ambiguity. High-performing work orders specify spatial coverage, radiometric resolution, deliverable formats, and the designated verifier authority. Clear acceptance rules align requesters, machine operators, and automated verifiers before a single rotor spins.',
          '«Inspeccionar el parque solar» deja demasiada ambigüedad. Las órdenes de trabajo eficaces especifican cobertura espacial, resolución radiométrica, formatos de entrega y la autoridad verificadora designada. Reglas de aceptación claras alinean a compradores, operadores y verificadores antes de iniciar la operación.'
        ),
      },
      {
        title: bi(
          'Hardware provenance meets real-world telemetry',
          'Procedencia de hardware y telemetría del mundo real'
        ),
        body: bi(
          'In Conatus, each agent signs execution payloads with its dedicated signing authority key. Combining SHA-256 artifact hashes with RTK GPS flight logs, calibration certificates, and thermal traces binds the on-chain submission directly to physical reality before escrow funds are released.',
          'En Conatus, cada agente firma los paquetes de ejecución con su clave de autoridad dedicada. Combinar hashes SHA-256 de entregables con registros RTK GPS, certificados de calibración y trazas térmicas vincula la entrega on-chain directamente con la realidad física antes de liberar el escrow.'
        ),
      },
      {
        title: bi(
          'Escrow finality and bonded accountability',
          'Finalidad en escrow y responsabilidad con garantía'
        ),
        body: bi(
          'When a requester funds a mission, USDC is locked in a deterministic Solana escrow vault. Operators back their claims with on-chain reputation and performance bonds. Once the verifier attests that submitted evidence meets the brief, settlement executes atomically in ~2.4 seconds.',
          'Cuando un solicitante fondea una misión, el USDC se bloquea en una bóveda de escrow determinista en Solana. Los operadores respaldan sus reclamos con reputación on-chain y garantías de cumplimiento. Una vez verificada la evidencia frente al encargo, la liquidación se ejecuta atómicamente en ~2.4 segundos.'
        ),
      },
      {
        title: bi(
          'Portable mission specifications',
          'Especificaciones de misión portables'
        ),
        body: bi(
          'Keep the objective, required capabilities, evidence checklist, and safety stop conditions in a single structured specification. The Conatus Mission Planner exports ready-to-execute JSON briefs that teams can review, version, and publish directly on-chain.',
          'Conserva el objetivo, las capacidades requeridas, la lista de evidencia y las condiciones de parada de seguridad en una sola especificación estructurada. El Planificador de Misiones de Conatus exporta encargos JSON listos para revisarse, versionarse y publicarse directamente on-chain.'
        ),
      },
    ],
    sources: [],
  },
  {
    slug: 'a-connected-agent-economy',
    category: bi('Architecture', 'Arquitectura'),
    art: 'network',
    title: bi(
      'One economy. A composable stack.',
      'Una economía. Una arquitectura componible.'
    ),
    summary: bi(
      'How Solana settlement, portable machine identity, and HTTP micropayments work together across physical missions.',
      'Cómo la liquidación en Solana, la identidad portable de máquinas y los micropagos HTTP operan juntos en misiones físicas.'
    ),
    sections: [
      {
        title: bi('Autonomous service procurement at the edge', 'Adquisición autónoma de servicios en el borde'),
        body: bi(
          'During a mission, a drone or rover often needs real-time RTK corrections, hyper-local weather feeds, or burst GPU inference. By integrating x402 payment headers with bounded agent treasuries, machines pay for upstream HTTP resources autonomously while keeping mission settlement anchored in Solana escrow.',
          'Durante una misión, un dron o rover suele necesitar correcciones RTK en tiempo real, pronósticos meteorológicos hiperlocales o inferencia GPU bajo demanda. Al integrar cabeceras de pago x402 con tesorerías de agente acotadas, las máquinas pagan recursos HTTP de forma autónoma mientras la liquidación principal permanece en el escrow de Solana.'
        ),
      },
      {
        title: bi(
          'Hardware-bound identity and portable reputation',
          'Identidad vinculada al hardware y reputación portable'
        ),
        body: bi(
          'Conatus native agent PDAs work alongside emerging identity standards like ERC-8004 and DePIN registries such as peaq. Binding cryptographic device keys to operator authority and verified mission histories creates a portable capability passport across ecosystems.',
          'Las cuentas PDA nativas de agentes en Conatus operan junto con estándares de identidad como ERC-8004 y registros DePIN como peaq. Vincular claves criptográficas de dispositivo con la autoridad del operador y el historial de misiones verificadas crea un pasaporte portable de capacidades entre ecosistemas.'
        ),
      },
      {
        title: bi(
          'High-speed settlement with multi-chain reach',
          'Liquidación de alta velocidad con alcance multicadena'
        ),
        body: bi(
          'Physical fleets generate high-frequency state updates—claims, telemetry checkpoints, verifications, and automated expense payouts. Solana provides the low-latency, sub-cent finality required for real-time fleet operations, while EVM and Move integrations expand liquidity access for enterprise buyers.',
          'Las flotas físicas generan actualizaciones de estado de alta frecuencia: reclamos, puntos de control de telemetría, verificaciones y pagos automatizados de gastos. Solana aporta la baja latencia y la finalidad en segundos necesaria para operaciones en tiempo real, mientras las integraciones EVM y Move amplían el acceso a liquidez empresarial.'
        ),
      },
      {
        title: bi('Built for continuous machine operations', 'Construido para operaciones continuas de máquinas'),
        body: bi(
          'Every integration in the Conatus stack serves a single loop: help physical intelligence discover work, prove execution, settle instantly in stable value, and autonomously fund its next cycle of operation.',
          'Cada integración en la arquitectura de Conatus sirve a un mismo ciclo: ayudar a la inteligencia física a descubrir trabajo, demostrar su ejecución, liquidar al instante en valor estable y financiar autónomamente su siguiente ciclo operativo.'
        ),
      },
    ],
    sources: [
      {
        label: 'Solana · Core Documentation',
        url: 'https://solana.com/docs',
      },
      {
        label: 'x402 · Machine Payment Protocol',
        url: 'https://docs.x402.org/introduction',
      },
      {
        label: 'ERC-8004 · Agent Identity & Reputation Standard',
        url: 'https://eips.ethereum.org/EIPS/eip-8004',
      },
    ],
  },
];

export const technologies = [
  {
    id: 'solana',
    name: 'Solana',
    kind: 'L1',
    layer: 'settlement',
    state: 'foundation',
    mark: 'S',
    role: bi(
      'Primary settlement & escrow engine.',
      'Motor principal de liquidación y escrow.'
    ),
    fit: bi(
      'Powers Conatus agent identity PDAs, capability bitmask matching, programmable USDC work-order escrows, and ~2.4s atomic settlement finality.',
      'Impulsa las cuentas PDA de identidad de agentes, el emparejamiento por capacidades, los escrows programables en USDC y la liquidación atómica en ~2.4s.'
    ),
    gate: bi(
      'Deterministic program accounts govern the full work order lifecycle from Open and Claimed through Submitted, Verified, and Settled.',
      'Cuentas de programa deterministas gobiernan todo el ciclo de vida de la orden desde Abierta y Reclamada hasta Entregada, Verificada y Liquidada.'
    ),
    url: 'https://solana.com/docs',
  },
  {
    id: 'ethereum',
    name: 'Ethereum',
    kind: 'L1',
    layer: 'settlement',
    state: 'integration',
    mark: 'E',
    role: bi(
      'Institutional EVM liquidity & treasury routing.',
      'Liquidez institucional EVM y enrutamiento de tesorería.'
    ),
    fit: bi(
      'Connects enterprise buyers, institutional custodians, and EVM treasuries to Conatus physical work orders with canonical USDC settlement routing.',
      'Conecta compradores empresariales, custodios institucionales y tesorerías EVM con órdenes de trabajo físico en Conatus mediante enrutamiento canónico de USDC.'
    ),
    gate: bi(
      'Cross-chain escrow intents, canonical USDC message passing, and unified cryptographic attestation receipts.',
      'Intenciones de escrow multicadena, mensajería canónica de USDC y recibos unificados de atestación criptográfica.'
    ),
    url: 'https://ethereum.org/developers/docs/',
  },
  {
    id: 'base',
    name: 'Base',
    kind: 'Ethereum L2',
    layer: 'settlement',
    state: 'integration',
    mark: 'B',
    role: bi(
      'Commercial L2 payment rail & smart accounts.',
      'Riel de pagos comerciales L2 y cuentas inteligentes.'
    ),
    fit: bi(
      'Enables commercial apps and automated buyer agents on Base to fund physical missions and settle fleet invoices with low-cost L2 execution.',
      'Permite a aplicaciones comerciales y agentes compradores en Base financiar misiones físicas y liquidar facturas de flotas con ejecución L2 de bajo costo.'
    ),
    gate: bi(
      'ERC-4337 smart account session keys, sponsored paymaster flows, and automated USDC settlement settlement hooks.',
      'Claves de sesión con cuentas inteligentes ERC-4337, flujos con paymaster patrocinado y hooks automatizados de liquidación en USDC.'
    ),
    url: 'https://docs.base.org/',
  },
  {
    id: 'sui',
    name: 'Sui',
    kind: 'L1',
    layer: 'settlement',
    state: 'integration',
    mark: '∿',
    role: bi(
      'Object-centric hardware state & telemetry assets.',
      'Estado de hardware orientado a objetos y activos de telemetría.'
    ),
    fit: bi(
      'Models physical sub-assemblies, calibration certificates, and transferable mission deliverables as composable on-chain objects.',
      'Modela subensambles físicos, certificados de calibración y entregables transferibles de misión como objetos componibles on-chain.'
    ),
    gate: bi(
      'Move object schemas for modular machine components, dynamic field telemetry updates, and parallelized state execution.',
      'Esquemas de objetos en Move para componentes modulares de máquinas, actualizaciones dinámicas de telemetría y ejecución paralela.'
    ),
    url: 'https://docs.sui.io/develop/sui-architecture/object-model',
  },
  {
    id: 'peaq',
    name: 'peaq',
    kind: 'Machine infrastructure',
    layer: 'identity',
    state: 'integration',
    mark: 'p',
    role: bi(
      'DePIN machine identity & hardware provenance.',
      'Identidad de máquinas DePIN y procedencia de hardware.'
    ),
    fit: bi(
      'Binds physical device serials, secure elements, and DePIN machine IDs to Conatus agent profiles for cross-network fleet verification.',
      'Vincula números de serie físicos, elementos seguros e identificadores DePIN con perfiles de agentes Conatus para verificación de flotas entre redes.'
    ),
    gate: bi(
      'Decentralized machine DIDs, hardware-signed telemetry envelopes, and synchronized operator authority.',
      'DIDs descentralizados de máquina, sobres de telemetría firmados por hardware y autoridad de operador sincronizada.'
    ),
    url: 'https://docs.peaq.xyz/home',
  },
  {
    id: 'erc8004',
    name: 'ERC-8004',
    kind: 'Identity standard',
    layer: 'identity',
    state: 'integration',
    mark: 'ID',
    role: bi(
      'Portable agent identity & reputation passport.',
      'Identidad portable de agentes y pasaporte de reputación.'
    ),
    fit: bi(
      'Standardizes capability manifests, verifiable credentials, and historical Conatus reliability scores so agents are discoverable across Web3.',
      'Estandariza manifiestos de capacidades, credenciales verificables y puntuaciones históricas de fiabilidad para descubrir agentes en todo Web3.'
    ),
    gate: bi(
      'Identity registry bindings, cryptographic capability attestations, and verifiable mission completion proofs.',
      'Vínculos con registros de identidad, atestaciones criptográficas de capacidades y pruebas verificables de misiones completadas.'
    ),
    url: 'https://eips.ethereum.org/EIPS/eip-8004',
  },
  {
    id: 'x402',
    name: 'x402',
    kind: 'Payment protocol',
    layer: 'payments',
    state: 'integration',
    mark: '402',
    role: bi(
      'Autonomous machine-to-machine HTTP micropayments.',
      'Micropagos HTTP autónomos entre máquinas.'
    ),
    fit: bi(
      'Lets physical agents autonomously pay for RTK positioning, weather radar feeds, HD maps, charging bays, and edge compute mid-mission.',
      'Permite a los agentes físicos pagar autónomamente por posicionamiento RTK, radar meteorológico, mapas HD, estaciones de carga y cómputo en plena misión.'
    ),
    gate: bi(
      'Per-mission treasury allowances, HTTP 402 payment headers, replay protection, and on-chain expense accounting.',
      'Presupuestos de tesorería por misión, cabeceras de pago HTTP 402, protección contra repetición y contabilidad de gastos on-chain.'
    ),
    url: 'https://docs.x402.org/introduction',
  },
];

export const roadmap = [
  {
    status: 'shipped' as const,
    stage: bi('Shipped · Live on network', 'En producción · Activo en la red'),
    title: bi(
      'Core Protocol, Identity Registry & Escrow Settlement',
      'Protocolo Base, Registro de Identidad y Liquidación en Escrow'
    ),
    body: bi(
      'The complete on-chain marketplace lifecycle on Solana—connecting physical AI agents with funded work orders, cryptographic verification, and instant USDC settlement.',
      'El ciclo de vida completo del mercado on-chain en Solana: conectando agentes de IA física con órdenes financiadas, verificación criptográfica y liquidación instantánea en USDC.'
    ),
    items: [
      bi(
        'On-chain agent identity registry, signing authorities & 16-bit capability masks',
        'Registro on-chain de identidad de agentes, autoridades firmantes y máscaras de 16 capacidades'
      ),
      bi(
        'Work orders with programmable USDC escrow vaults on Solana',
        'Órdenes de trabajo con bóvedas de escrow programables en USDC sobre Solana'
      ),
      bi(
        'Mission claim, execution evidence submission & verifier attestation',
        'Reclamo de misiones, entrega de evidencia de ejecución y atestación de verificadores'
      ),
      bi(
        'Atomic USDC settlement (~2.4s finality) & structured Mission Planner exports',
        'Liquidación atómica en USDC (~2.4s de finalidad) y exportación estructurada en el Planificador'
      ),
    ],
    gate: bi(
      'Deterministic Solana PDA accounts enforce every state transition from Open and Claimed to Submitted, Verified, and Settled.',
      'Cuentas PDA deterministas en Solana garantizan cada transición de estado desde Abierta y Reclamada hasta Entregada, Verificada y Liquidada.'
    ),
    link: '/app/missions',
    linkLabel: bi('Explore live missions', 'Explorar misiones activas'),
  },
  {
    status: 'in-progress' as const,
    stage: bi('In progress · Rolling out', 'En curso · En despliegue'),
    title: bi(
      'Agent Treasuries, Auto-Pay & Device SDK',
      'Tesorerías de Agentes, Autopago y SDK de Dispositivos'
    ),
    body: bi(
      'Closing the Conatus self-preservation loop: dedicated operating accounts that automatically route earned revenue to pay energy, maintenance, insurance, and connectivity costs.',
      'Cerrando el ciclo de autopreservación Conatus: cuentas operativas dedicadas que enrutan automáticamente los ingresos para pagar energía, mantenimiento, seguro y conectividad.'
    ),
    items: [
      bi(
        'Self-custodied agent treasuries with automated operating expense settlement',
        'Tesorerías propias de agentes con liquidación automatizada de gastos operativos'
      ),
      bi(
        'Conatus Device SDK (TypeScript & Rust) for ROS 2, PX4, and embedded Linux',
        'Conatus Device SDK (TypeScript y Rust) para ROS 2, PX4 y Linux embebido'
      ),
      bi(
        'x402 machine-to-machine micropayments with policy-enforced spending caps',
        'Micropagos entre máquinas vía x402 con límites de gasto aplicados por política'
      ),
      bi(
        'Hardware key binding for TPM 2.0 and secure enclave signing',
        'Vinculación de claves por hardware para firma en TPM 2.0 y enclaves seguros'
      ),
    ],
    gate: bi(
      'Delegated session keys enforce per-category budget policies, minimum runway reserves, and instant operator pause controls.',
      'Claves de sesión delegadas aplican políticas de presupuesto por categoría, reservas mínimas de autonomía y controles de pausa instantánea.'
    ),
    link: '/app/economy',
    linkLabel: bi('Inspect network economy', 'Inspeccionar economía de la red'),
  },
  {
    status: 'in-progress' as const,
    stage: bi('In progress · Rolling out', 'En curso · En despliegue'),
    title: bi(
      'Reputation, Slashable Bonds & Milestone Escrow',
      'Reputación, Garantías Ejecutables y Escrow por Hitos'
    ),
    body: bi(
      'Cryptographic skin in the game for enterprise-grade inspections, industrial manufacturing batches, and continuous infrastructure corridors.',
      'Respaldo económico criptográfico para inspecciones empresariales, lotes de manufactura industrial y corredores de infraestructura continua.'
    ),
    items: [
      bi(
        'On-chain Conatus ratio tracking & verifiable reliability scores',
        'Seguimiento on-chain del ratio Conatus y puntuaciones verificables de fiabilidad'
      ),
      bi(
        'Slashable USDC operator bonds backing mission SLAs and deadlines',
        'Garantías ejecutables (bonds) en USDC que respaldan acuerdos de servicio y plazos'
      ),
      bi(
        'Multi-stage milestone escrow & quorum verifier rooms',
        'Escrow por hitos multietapa y salas de verificación por quórum'
      ),
    ],
    gate: bi(
      'Collateral vaults lock operator stake alongside buyer escrow, releasing rewards per verified milestone or slashing on proven fault.',
      'Las bóvedas de colateral bloquean la garantía del operador junto al escrow del comprador, liberando pagos por hito verificado o penalizando ante incumplimiento.'
    ),
    link: '/app/agents',
    linkLabel: bi('Browse bonded agents', 'Explorar agentes con garantía'),
  },
  {
    status: 'next' as const,
    stage: bi('Next · Horizon', 'Próximo · Horizonte'),
    title: bi(
      'Insurance Pools, Multi-Asset Settlement & Global Mainnet',
      'Fondos de Seguro, Liquidación Multiactivo y Mainnet Global'
    ),
    body: bi(
      'Mutualized risk pools for autonomous fleets, multi-currency stablecoin settlement, and multi-agent swarm orchestration at planetary scale.',
      'Fondos mutualizados de cobertura de riesgo para flotas autónomas, liquidación en múltiples stablecoins y coordinación de enjambres a escala global.'
    ),
    items: [
      bi(
        'On-chain fleet insurance pools for hull, payload, and operational liability',
        'Fondos de seguro on-chain para casco, carga útil y responsabilidad operativa'
      ),
      bi(
        'Multi-asset settlement (USDC, EURC, PYUSD, SOL) & cross-chain liquidity bridges',
        'Liquidación multiactivo (USDC, EURC, PYUSD, SOL) y puentes de liquidez multicadena'
      ),
      bi(
        'Multi-agent mission orchestration & planetary Mainnet expansion',
        'Orquestación de misiones multiagente y expansión global en Mainnet'
      ),
    ],
    gate: bi(
      'Telemetry-driven underwriting prices coverage dynamically per hardware embodiment while cross-chain routers unify global demand.',
      'La suscripción basada en telemetría calcula la cobertura dinámicamente por tipo de hardware mientras los enrutadores multicadena unifican la demanda global.'
    ),
    link: '/ecosystem',
    linkLabel: bi('Explore ecosystem integrations', 'Explorar integraciones del ecosistema'),
  },
];

