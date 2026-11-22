/** The system at a glance: same content as the Mermaid chart in docs/architecture.md. */
export function ArchitectureDiagram() {
  const box = 'fill-[var(--surface)] stroke-[var(--border-strong)]'
  const label = 'fill-[var(--text)] text-[13px] font-medium'
  const note = 'fill-[var(--muted)] text-[11px]'
  const line = 'stroke-[var(--faint)]'
  return (
    <svg
      viewBox="0 0 880 330"
      role="img"
      aria-labelledby="arch-title arch-desc"
      className="h-auto w-full min-w-[640px]"
    >
      <title id="arch-title">GateSense architecture</title>
      <desc id="arch-desc">
        A camera feeds the ANPR worker at the gate, which posts plate reads to the FastAPI backend.
        The backend stores data in PostgreSQL, Redis and object storage. Celery workers send email
        and Telegram messages. The web app gets live updates over a WebSocket.
      </desc>
      <defs>
        <marker
          id="arrow"
          viewBox="0 0 10 10"
          refX="9"
          refY="5"
          markerWidth="7"
          markerHeight="7"
          orient="auto-start-reverse"
        >
          <path d="M0 0L10 5L0 10z" className="fill-[var(--faint)]" />
        </marker>
      </defs>
      <rect
        x="10"
        y="20"
        width="250"
        height="290"
        rx="12"
        className="fill-[var(--surface-2)] stroke-[var(--border)]"
        strokeDasharray="4 4"
      />
      <text x="26" y="44" className={note}>
        At the gate (edge)
      </text>

      <rect x="30" y="64" width="210" height="54" rx="10" className={box} />
      <text x="46" y="88" className={label}>
        Camera
      </text>
      <text x="46" y="106" className={note}>
        entry and exit lanes
      </text>

      <rect x="30" y="148" width="210" height="62" rx="10" className={box} />
      <text x="46" y="172" className={label}>
        ANPR worker
      </text>
      <text x="46" y="190" className={note}>
        YOLOv8 + OCR on ONNX Runtime
      </text>

      <rect x="30" y="240" width="210" height="50" rx="10" className={box} />
      <text x="46" y="262" className={label}>
        Offline buffer
      </text>
      <text x="46" y="279" className={note}>
        SQLite, replays in order
      </text>

      <line x1="135" y1="118" x2="135" y2="146" className={line} markerEnd="url(#arrow)" />
      <line x1="135" y1="210" x2="135" y2="238" className={line} markerEnd="url(#arrow)" />

      <rect
        x="330"
        y="130"
        width="200"
        height="86"
        rx="10"
        className="fill-[var(--accent-soft)] stroke-[var(--accent)]"
      />
      <text x="348" y="158" className={label}>
        FastAPI backend
      </text>
      <text x="348" y="177" className={note}>
        plate matching, visit state
      </text>
      <text x="348" y="194" className={note}>
        machine, approvals, auth
      </text>
      <line x1="240" y1="179" x2="328" y2="173" className={line} markerEnd="url(#arrow)" />
      <text x="252" y="164" className={note}>
        HTTPS + key
      </text>

      <rect x="600" y="20" width="130" height="46" rx="10" className={box} />
      <text x="616" y="48" className={label}>
        PostgreSQL
      </text>
      <rect x="600" y="84" width="130" height="46" rx="10" className={box} />
      <text x="616" y="112" className={label}>
        Redis
      </text>
      <rect x="600" y="148" width="130" height="46" rx="10" className={box} />
      <text x="616" y="168" className={label}>
        Snapshots
      </text>
      <text x="616" y="184" className={note}>
        S3-compatible
      </text>
      <line x1="530" y1="150" x2="598" y2="45" className={line} markerEnd="url(#arrow)" />
      <line x1="530" y1="160" x2="598" y2="108" className={line} markerEnd="url(#arrow)" />
      <line x1="530" y1="172" x2="598" y2="171" className={line} markerEnd="url(#arrow)" />

      <rect x="600" y="222" width="170" height="54" rx="10" className={box} />
      <text x="616" y="245" className={label}>
        Celery worker + Beat
      </text>
      <text x="616" y="263" className={note}>
        escalation, retention, mail
      </text>
      <path
        d="M730 107H752V220"
        fill="none"
        className={line}
        markerEnd="url(#arrow)"
        strokeDasharray="3 3"
      />
      <rect x="790" y="210" width="80" height="34" rx="8" className={box} />
      <text x="806" y="232" className={note}>
        Email
      </text>
      <rect x="790" y="256" width="80" height="34" rx="8" className={box} />
      <text x="806" y="278" className={note}>
        Telegram
      </text>
      <line x1="770" y1="240" x2="788" y2="228" className={line} markerEnd="url(#arrow)" />
      <line x1="770" y1="256" x2="788" y2="270" className={line} markerEnd="url(#arrow)" />

      <rect x="330" y="262" width="200" height="54" rx="10" className={box} />
      <text x="348" y="285" className={label}>
        Web app (React)
      </text>
      <text x="348" y="303" className={note}>
        guard, resident, admin
      </text>
      <line
        x1="430"
        y1="216"
        x2="430"
        y2="260"
        className={line}
        markerEnd="url(#arrow)"
        markerStart="url(#arrow)"
      />
      <text x="438" y="243" className={note}>
        WebSocket
      </text>
    </svg>
  )
}
