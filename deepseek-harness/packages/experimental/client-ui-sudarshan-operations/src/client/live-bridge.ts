import type {
  ArtifactProjection,
  ArtifactType,
  OperationsBridge,
  OperatorProjection,
  ProjectionStatus,
  TelemetryProjection,
} from './projection.ts'

export interface LiveBridgeConfig {
  apiOrigin?: string
  fetcher?: typeof globalThis.fetch
  eventSource?: typeof globalThis.EventSource
}

type JsonObject = Record<string, unknown>

const DEFAULT_API_ORIGIN = 'http://localhost:8000'
const RUN_KEY_PREFIX = 'sudarshan.operations.run.'
const CURSOR_KEY_PREFIX = 'sudarshan.operations.cursor.'
const toolNamesBySession = new Map<string, Map<string, string>>()

function apiOrigin(config: LiveBridgeConfig): string {
  const configured = config.apiOrigin
    ?? (globalThis as typeof globalThis & { SUDARSHAN_API_ORIGIN?: string }).SUDARSHAN_API_ORIGIN
    ?? DEFAULT_API_ORIGIN
  return configured.replace(/\/$/, '')
}

function runKey(sessionId: string): string {
  return `${RUN_KEY_PREFIX}${sessionId}`
}

function cursorKey(sessionId: string): string {
  return `${CURSOR_KEY_PREFIX}${sessionId}`
}

function readRunId(sessionId: string): string {
  try { return globalThis.sessionStorage.getItem(runKey(sessionId)) || sessionId } catch { return sessionId }
}

function writeRunId(sessionId: string, runId: string): void {
  try { globalThis.sessionStorage.setItem(runKey(sessionId), runId) } catch { /* storage is optional */ }
}

function readCursor(sessionId: string): number {
  try {
    const value = Number(globalThis.sessionStorage.getItem(cursorKey(sessionId)) || 0)
    return Number.isInteger(value) && value > 0 ? value : 0
  } catch { return 0 }
}

function writeCursor(sessionId: string, sequence: number): void {
  if (!Number.isInteger(sequence) || sequence <= 0) return
  try {
    const current = readCursor(sessionId)
    if (sequence > current) globalThis.sessionStorage.setItem(cursorKey(sessionId), String(sequence))
  } catch { /* storage is optional */ }
}

function text(value: unknown, fallback = ''): string {
  return typeof value === 'string' && value.trim() ? value : fallback
}

function number(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, Math.min(100, value)) : fallback
}

function count(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? Math.max(0, value) : fallback
}

function normalizedStatus(value: unknown, stage = '', waitReason = ''): ProjectionStatus {
  const raw = text(value, 'queued').toLowerCase()
  const context = `${stage} ${waitReason}`.toLowerCase()
  if (raw === 'cancelled' || raw === 'canceled') return 'cancelled'
  if (raw === 'retrying' || raw === 'retry') return 'retry'
  if (raw === 'pending' || raw === 'provider_pending' || raw === 'provider-pending') return 'provider-pending'
  if (raw === 'waiting_for_approval' || raw === 'approval') return 'approval'
  if (raw === 'waiting_for_input' || raw === 'waiting') return 'waiting'
  if (raw === 'waiting_on_dependency' || raw === 'waiting_on_child_skill') {
    return /capacity|concurrency|queue|worker/.test(context) ? 'capacity-wait' : 'waiting'
  }
  if (raw === 'queued' && /capacity|concurrency|queue wait|worker/.test(context)) return 'capacity-wait'
  if (raw === 'accepted' || raw === 'planning' || raw === 'validating' || raw === 'rendering' || raw === 'quality_check' || raw === 'repairing') return 'running'
  if (raw === 'completed') return 'succeeded'
  if (raw === 'partial') return 'partial'
  if (raw === 'failed' || raw === 'cancelled') return 'failed'
  if (raw === 'running' || raw === 'waiting' || raw === 'succeeded') return raw
  return 'queued'
}

function sequence(value: unknown): number | undefined {
  if (!value || typeof value !== 'object') return undefined
  const candidate = (value as JsonObject).sequence
  return typeof candidate === 'number' && Number.isInteger(candidate) && candidate > 0 ? candidate : undefined
}

function artifactType(value: unknown): ArtifactType {
  const raw = text(value, 'markdown').toLowerCase()
  if (raw.includes('ppt') || raw.includes('presentation') || raw.includes('slide')) return 'presentation'
  if (raw.includes('infographic') || raw.includes('svg')) return 'infographic'
  if (raw.includes('video') || raw.includes('mp4')) return 'video'
  if (raw.includes('linkedin')) return 'linkedin'
  return 'markdown'
}

function size(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—'
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

function uri(value: unknown): string | undefined {
  if (typeof value !== 'string' || !value.startsWith('/')) return undefined
  return value
}

function projectionFromPayload(payload: JsonObject, runId: string): OperatorProjection {
  const summary = (payload.summary ?? {}) as JsonObject
  const telemetry = (payload.telemetry ?? {}) as JsonObject
  const summaryTelemetry = (summary.telemetry ?? {}) as JsonObject
  const responseItems = Array.isArray(payload.responses) ? payload.responses : []
  const rawArtifacts = Array.isArray(payload.artifacts) ? payload.artifacts : (Array.isArray(payload.artifact_manifests) ? payload.artifact_manifests : [])
  const rawIngestion = Array.isArray(payload.ingestion_stages) ? payload.ingestion_stages : []
  const rawEvidence = Array.isArray(payload.evidence) ? payload.evidence : []
  const rawChildren = Array.isArray(payload.children) ? payload.children : responseItems

  const artifacts: ArtifactProjection[] = rawArtifacts.map((item, index) => {
    const value = (item ?? {}) as JsonObject
    const hasArtifactId = typeof value.artifact_id === 'string' || typeof value.id === 'string'
    const artifactId = text(value.artifact_id ?? value.id, `${runId}-artifact-${index + 1}`)
    const previewUri = uri(value.preview_uri)
    const downloadUri = uri(value.download_uri ?? value.uri) ?? (hasArtifactId ? `/artifacts/${artifactId}/download` : undefined)
    const quality = text(value.quality_status, 'ready')
    return {
      id: artifactId,
      name: text(value.name ?? value.filename, artifactId),
      type: artifactType(value.kind ?? value.artifact_type ?? value.type),
      status: quality === 'blocked' || quality === 'failed' ? 'blocked' : quality === 'partial' ? 'partial' : quality === 'quality-review' || quality === 'pending' ? 'quality-review' : 'ready',
      renderer: text(value.renderer, 'sudarshan-renderer'),
      version: text(value.renderer_version ?? value.version, '1.0'),
      size: size(value.size_bytes ?? value.size),
      classification: text(value.classification_level ?? value.classification, 'INTERNAL'),
      previewAvailable: Boolean(value.preview_available ?? previewUri),
      ...(previewUri ? { previewUri } : {}),
      ...(downloadUri ? { downloadUri } : {}),
      ...(typeof value.repair === 'string' ? { repair: value.repair } : {}),
    }
  })

  return {
    runId: text(payload.run_id, runId),
    taskId: text(payload.task_id, runId),
    status: normalizedStatus(payload.status ?? summary.status, text(payload.stage ?? summary.stage), text(payload.wait_reason ?? summary.wait_reason)),
    stage: text(payload.stage ?? summary.stage, 'Sudarshan run'),
    progress: number(payload.progress ?? telemetry.progress),
    queue: text(payload.queue, 'sudarshan'),
    waitReason: text(payload.wait_reason ?? summary.wait_reason, 'No active wait.'),
    children: rawChildren.map((item, index) => {
      const value = (item ?? {}) as JsonObject
      return {
        id: text(value.id ?? value.task_id, `child-${index + 1}`),
        label: text(value.label ?? value.pipeline, 'Child task'),
        status: normalizedStatus(value.status, text(value.stage ?? value.pipeline), text(value.wait_reason)),
        progress: number(value.progress),
        pipeline: text(value.pipeline, 'sudarshan'),
        ...(typeof value.wait_reason === 'string' ? { waitReason: value.wait_reason } : {}),
      }
    }),
    evidence: rawEvidence.map((item, index) => {
      const value = (item ?? {}) as JsonObject
      return {
        id: text(value.id, `evidence-${index + 1}`),
        sourceReference: text(value.source_reference ?? value.source, 'source://unknown'),
        location: text(value.location, 'unknown location'),
        confidence: text(value.confidence, '—'),
        provenance: text(value.provenance, 'sudarshan'),
        classification: text(value.classification, 'INTERNAL'),
      }
    }),
    artifacts,
    ingestionStages: rawIngestion.map((item) => {
      const value = (item ?? {}) as JsonObject
      return { label: text(value.label ?? value.stage, 'Ingestion stage'), status: normalizedStatus(value.status, text(value.stage), text(value.detail)), detail: text(value.detail, '') }
    }),
    telemetry: telemetryProjection(telemetry, summaryTelemetry, payload),
    qualityStatus: text(payload.quality_status ?? summary.quality_status, 'pending'),
    fallbacks: Array.isArray(payload.fallbacks) ? payload.fallbacks.filter((value): value is string => typeof value === 'string' && value.trim().length > 0) : [],
    generatedAt: text(payload.generated_at, new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })),
  }
}

function telemetryProjection(telemetry: JsonObject, summary: JsonObject, payload: JsonObject): TelemetryProjection {
  const value = (key: string, fallback = 0): number => count(telemetry[key] ?? summary[key] ?? payload[key], fallback)
  return {
    queueWaitMs: value('queue_wait_ms'),
    inputTokens: value('input_tokens'),
    outputTokens: value('output_tokens'),
    reasoningTokens: value('reasoning_tokens'),
    estimatedCost: value('estimated_cost'),
    usageIsEstimate: Boolean(telemetry.usage_is_estimate ?? summary.usage_is_estimate ?? payload.usage_is_estimate),
    cacheHits: value('cache_hits'),
    cacheWaits: value('cache_waits'),
    fallbackCount: value('fallback_count'),
  }
}

function openArtifact(origin: string, path: string | undefined): void {
  if (!path || !path.startsWith('/')) return
  globalThis.open?.(`${origin}${path}`, '_blank', 'noopener,noreferrer')
}

export function createLiveOperationsBridge(config: LiveBridgeConfig = {}): OperationsBridge {
  const origin = apiOrigin(config)
  const fetcher = config.fetcher ?? globalThis.fetch.bind(globalThis)
  const EventSourceCtor = config.eventSource ?? globalThis.EventSource

  const getProjection = async (sessionId: string): Promise<OperatorProjection> => {
    const runId = readRunId(sessionId)
    const response = await fetcher(`${origin}/runs/${encodeURIComponent(runId)}`)
    if (!response.ok) throw new Error(`Sudarshan status request failed: ${response.status}`)
    const payload = await response.json() as JsonObject
    if (!Array.isArray(payload.artifacts) && !Array.isArray(payload.artifact_manifests)) {
      const pipelines = Array.isArray(payload.pipelines)
        ? payload.pipelines
        : (typeof payload.pipeline === 'string' ? [payload.pipeline] : [])
      const terminal = ['succeeded', 'partial', 'failed', 'cancelled', 'completed'].includes(text(payload.status))
      if (terminal) {
        const manifests = await Promise.all(pipelines.map(async value => {
          const key = text(value).toLowerCase() === 'ppt' ? 'presentation' : text(value).toLowerCase()
          if (!key) return null
          const manifest = await fetcher(`${origin}/artifacts/${encodeURIComponent(runId)}/${encodeURIComponent(key)}/manifest`)
          return manifest.ok ? await manifest.json() as JsonObject : null
        }))
        payload.artifact_manifests = manifests.filter(Boolean)
      }
    }
    if (Array.isArray(payload.events)) {
      for (const event of payload.events) {
        const current = sequence(event)
        if (current !== undefined) writeCursor(sessionId, current)
      }
    }
    return projectionFromPayload(payload, runId)
  }

  return {
    getProjection,
    bindRun(sessionId, runId) {
      if (!sessionId || !runId) return
      if (readRunId(sessionId) !== runId) {
        try { globalThis.sessionStorage.removeItem(cursorKey(sessionId)) } catch { /* storage is optional */ }
      }
      writeRunId(sessionId, runId)
    },
    subscribeProjection(sessionId, onProjection) {
      if (!EventSourceCtor) return () => undefined
      let source: EventSource | undefined
      let reconnectTimer: ReturnType<typeof setTimeout> | undefined
      let disposed = false
      const refresh = () => { void getProjection(sessionId).then(onProjection).catch(() => undefined) }
      const connect = (): void => {
        if (disposed) return
        const runId = readRunId(sessionId)
        source = new EventSourceCtor(`${origin}/runs/${encodeURIComponent(runId)}/events?after_sequence=${readCursor(sessionId)}`)
        source.addEventListener('progress', (event: Event) => {
          try {
            const parsed = JSON.parse((event as MessageEvent<string>).data) as unknown
            const current = sequence(parsed)
            if (current !== undefined) writeCursor(sessionId, current)
          } catch { /* malformed event data is ignored; status polling remains authoritative */ }
          refresh()
        })
        source.addEventListener('heartbeat', refresh)
        source.onerror = () => {
          source?.close()
          if (!disposed && reconnectTimer === undefined) {
            reconnectTimer = setTimeout(() => { reconnectTimer = undefined; connect() }, 1_000)
          }
        }
      }
      connect()
      return () => {
        disposed = true
        if (reconnectTimer !== undefined) clearTimeout(reconnectTimer)
        source?.close()
      }
    },
    previewArtifact(artifact) { openArtifact(origin, artifact.previewUri) },
    downloadArtifact(artifact) { openArtifact(origin, artifact.downloadUri) },
  }
}

function findRunId(value: unknown): string | undefined {
  if (Array.isArray(value)) {
    for (const item of value) {
      const found = findRunId(item)
      if (found) return found
    }
    return undefined
  }
  if (typeof value === 'string') {
    try { return findRunId(JSON.parse(value)) } catch { return undefined }
  }
  if (!value || typeof value !== 'object') return undefined
  const record = value as JsonObject
  if (typeof record.run_id === 'string' && record.run_id.trim()) return record.run_id
  for (const nested of Object.values(record)) {
    const found = findRunId(nested)
    if (found) return found
  }
  return undefined
}

/** Bind a native Harness session when the Sudarshan start tool settles. */
export function observeHarnessEvent(bridge: OperationsBridge, sessionId: string, event: unknown): void {
  if (!event || typeof event !== 'object') return
  const record = event as JsonObject
  const data = (record.data ?? {}) as JsonObject
  const type = text(record.type)
  const names = toolNamesBySession.get(sessionId) ?? new Map<string, string>()
  toolNamesBySession.set(sessionId, names)
  if (type === 'tool/call') {
    const callId = text(data.callId)
    const name = text(data.name)
    if (callId && name) names.set(callId, name)
    return
  }
  if (type !== 'tool/result') return
  const message = (data.message ?? {}) as JsonObject
  const source = (message.source ?? {}) as JsonObject
  const callId = text(source.callId ?? data.callId)
  const name = names.get(callId) ?? ''
  if (name !== 'start_sudarshan_run' && name !== 'run_sudarshan') return
  const runId = findRunId(message.content ?? data.content)
  if (runId) bridge.bindRun?.(sessionId, runId)
}

export function installLiveOperationsBridge(config: LiveBridgeConfig = {}): OperationsBridge {
  const current = (globalThis as typeof globalThis & { SudarshanOperationsBridge?: OperationsBridge }).SudarshanOperationsBridge
  if (current?.getProjection) return current
  const bridge = createLiveOperationsBridge(config)
  ;(globalThis as typeof globalThis & { SudarshanOperationsBridge?: OperationsBridge }).SudarshanOperationsBridge = bridge
  return bridge
}
