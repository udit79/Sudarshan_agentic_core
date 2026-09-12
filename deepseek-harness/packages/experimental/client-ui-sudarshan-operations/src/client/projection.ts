/**
 * Frontend-owned shape for the backend's safe run/artifact projection.
 * It deliberately contains references and measurements, never raw source text,
 * prompts, provider payloads, credentials, or hidden reasoning.
 */
export type ProjectionStatus = 'queued' | 'capacity-wait' | 'running' | 'waiting' | 'provider-pending' | 'approval' | 'retry' | 'succeeded' | 'partial' | 'failed' | 'cancelled'
export type ArtifactType = 'markdown' | 'presentation' | 'infographic' | 'video' | 'linkedin'

export interface ChildProjection {
  id: string
  label: string
  status: ProjectionStatus
  progress: number
  waitReason?: string
  pipeline: string
}

export interface EvidenceProjection {
  id: string
  sourceReference: string
  location: string
  confidence: string
  provenance: string
  classification: string
}

export interface ArtifactProjection {
  id: string
  name: string
  type: ArtifactType
  status: 'ready' | 'quality-review' | 'partial' | 'blocked'
  renderer: string
  version: string
  size: string
  classification: string
  qualityReportId?: string
  qualityIssues: readonly string[]
  degraded: boolean
  fallbackRenderer?: string
  comparison?: {
    previousPreviewUri?: string
    previousRenderer?: string
    previousVersion?: string
  }
  previewAvailable: boolean
  previewUri?: string
  downloadUri?: string
  repair?: string
}

export interface TelemetryProjection {
  queueWaitMs: number
  inputTokens: number
  outputTokens: number
  reasoningTokens: number
  estimatedCost: number
  usageIsEstimate: boolean
  cacheHits: number
  cacheWaits: number
  fallbackCount: number
}

export interface OperatorProjection {
  runId: string
  taskId: string
  status: ProjectionStatus
  stage: string
  progress: number
  queue: string
  waitReason: string
  children: readonly ChildProjection[]
  evidence: readonly EvidenceProjection[]
  artifacts: readonly ArtifactProjection[]
  ingestionStages: readonly { label: string; status: ProjectionStatus; detail: string }[]
  telemetry: TelemetryProjection
  qualityStatus: string
  fallbacks: readonly string[]
  generatedAt: string
}

export interface OperationsBridge {
  getProjection?: (sessionId: string) => Promise<OperatorProjection> | OperatorProjection
  subscribeProjection?: (sessionId: string, onProjection: (projection: OperatorProjection) => void) => (() => void)
  bindRun?: (sessionId: string, runId: string) => void
  previewArtifact?: (artifact: ArtifactProjection) => void
  downloadArtifact?: (artifact: ArtifactProjection) => void
  reviewArtifact?: (sessionId: string, artifact: ArtifactProjection, decision: 'approve' | 'reject', reason?: string) => void | Promise<void>
  retryIngestion?: (sessionId: string) => void
  cancelIngestion?: (sessionId: string) => void
}

declare global {
  var SudarshanOperationsBridge: OperationsBridge | undefined
}

export function getOperationsBridge(): OperationsBridge | undefined {
  return globalThis.SudarshanOperationsBridge
}

/** Deterministic fixture used until the typed backend projection is available. */
export function previewProjection(sessionId: string, refresh = 0): OperatorProjection {
  const suffix = sessionId.slice(-6) || 'local'
  const generatedAt = new Date(Date.now() - refresh * 1_000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  return {
    runId: `run-preview-${suffix}`,
    taskId: `task-preview-${suffix}`,
    status: 'running',
    stage: 'Routing context',
    progress: 68,
    queue: 'worker-02 · 0.8s',
    waitReason: 'Visual child is waiting for quality review.',
    children: [
      { id: 'context', label: 'Context & classification', status: 'succeeded', progress: 100, pipeline: 'context' },
      { id: 'brief', label: 'Executive brief', status: 'running', progress: 72, pipeline: 'advisory' },
      { id: 'visual', label: 'Presentation + infographic', status: 'waiting', progress: 54, waitReason: 'quality_review', pipeline: 'visual' },
      { id: 'video', label: 'Narrated video', status: 'queued', progress: 0, pipeline: 'video' },
    ],
    evidence: [
      { id: 'ev-014', sourceReference: 'source://case/briefing.pdf', location: 'page 4 · section 2', confidence: '0.94', provenance: 'retrieval · L1', classification: 'RESTRICTED' },
      { id: 'ev-021', sourceReference: 'source://case/metrics.xlsx', location: 'sheet Summary · B12:F18', confidence: '0.89', provenance: 'structured source', classification: 'RESTRICTED' },
      { id: 'ev-033', sourceReference: 'source://case/brand-kit', location: 'asset manifest · logo.svg', confidence: '1.00', provenance: 'operator supplied', classification: 'INTERNAL' },
    ],
    artifacts: [
      { id: 'art-brief', name: 'executive-brief.md', type: 'markdown', status: 'ready', renderer: 'markdown-safe', version: '1.3', size: '18 KB', classification: 'RESTRICTED', qualityIssues: [], degraded: false, previewAvailable: true },
      { id: 'art-deck', name: 'board-deck.pptx', type: 'presentation', status: 'quality-review', renderer: 'pptx-native', version: '2.1', size: '2.4 MB', classification: 'RESTRICTED', qualityIssues: ['Contrast on slide 4'], degraded: false, comparison: { previousRenderer: 'pptx-native', previousVersion: '2.0' }, previewAvailable: true, repair: '1 slide needs contrast review' },
      { id: 'art-infographic', name: 'metrics.svg', type: 'infographic', status: 'partial', renderer: 'svg-deterministic', version: '1.0', size: '86 KB', classification: 'RESTRICTED', qualityIssues: ['Missing source label on 1 chart'], degraded: true, fallbackRenderer: 'infographic.native-svg', previewAvailable: true, repair: 'Missing source label on 1 chart' },
      { id: 'art-video', name: 'briefing.mp4', type: 'video', status: 'blocked', renderer: 'video-compositor', version: '0.8', size: '—', classification: 'RESTRICTED', qualityIssues: [], degraded: true, fallbackRenderer: 'video.ffmpeg', previewAvailable: false, repair: 'Waiting for visual child' },
      { id: 'art-linkedin', name: 'linkedin-draft.md', type: 'linkedin', status: 'ready', renderer: 'linkedin-safe', version: '1.1', size: '9 KB', classification: 'RESTRICTED', qualityIssues: [], degraded: false, previewAvailable: true },
    ],
    ingestionStages: [
      { label: 'Upload receipt', status: 'succeeded', detail: '3 sources · 7.2 MB' },
      { label: 'Type + classification', status: 'succeeded', detail: 'RESTRICTED' },
      { label: 'Text extraction', status: 'succeeded', detail: 'PDF, XLSX, SVG' },
      { label: 'Memory persistence', status: 'running', detail: 'L1 projection pending' },
    ],
    telemetry: {
      queueWaitMs: 800,
      inputTokens: 4_820,
      outputTokens: 1_260,
      reasoningTokens: 640,
      estimatedCost: 0.18,
      usageIsEstimate: true,
      cacheHits: 4,
      cacheWaits: 1,
      fallbackCount: 1,
    },
    qualityStatus: 'repairable',
    fallbacks: ['Video child is using the native renderer fallback.'],
    generatedAt,
  }
}
