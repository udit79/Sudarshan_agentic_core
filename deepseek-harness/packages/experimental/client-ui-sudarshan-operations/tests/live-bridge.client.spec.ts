import { afterEach, describe, expect, it, vi } from 'vitest'
import { createLiveOperationsBridge, observeHarnessEvent } from '../src/client/live-bridge.ts'

class FakeEventSource {
  static instances: FakeEventSource[] = []
  readonly listeners = new Map<string, (event: Event) => void>()
  onerror: (() => void) | null = null
  closed = false

  constructor(readonly url: string) { FakeEventSource.instances.push(this) }

  addEventListener(type: string, listener: EventListenerOrEventListenerObject): void {
    this.listeners.set(type, listener as (event: Event) => void)
  }

  close(): void { this.closed = true }

  emit(type: string, data = ''): void {
    this.listeners.get(type)?.({ data } as MessageEvent<string>)
  }

  fail(): void { this.onerror?.() }
}

const storage = new Map<string, string>()
const sessionStorageMock = {
  getItem: (key: string) => storage.get(key) ?? null,
  setItem: (key: string, value: string) => { storage.set(key, value) },
  removeItem: (key: string) => { storage.delete(key) },
  clear: () => { storage.clear() },
}

afterEach(() => {
  FakeEventSource.instances = []
  storage.clear()
  vi.useRealTimers()
})

describe('Sudarshan live operations bridge', () => {
  it('hydrates terminal pipeline manifests through stable artifact routes', async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/runs/run-1')) {
        return new Response(JSON.stringify({ run_id: 'run-1', task_id: 'task-1', status: 'completed', pipeline: 'ppt', pipelines: ['ppt'] }), { status: 200 })
      }
      if (url.endsWith('/runs/run-1/resume')) return new Response('{}', { status: 202 })
      expect(url).toContain('/artifacts/run-1/presentation/manifest')
      return new Response(JSON.stringify({
        artifact_id: 'artifact-1', kind: 'presentation', name: 'deck.pptx',
        preview_uri: '/artifacts/artifact-1/preview', uri: '/artifacts/artifact-1/download',
        renderer_version: 'pptx-native@1', size_bytes: 1024, classification_level: 'RESTRICTED',
        quality_status: 'passed',
        quality_report_id: 'quality-1',
        issues: ['contrast on slide 4'],
        previous_preview_uri: '/artifacts/artifact-1/previous-preview',
        previous_renderer: 'pptx-legacy',
        previous_renderer_version: '0.9',
        metadata: { degraded: true, fallback_renderer_id: 'presentation.pptx' },
      }), { status: 200 })
    })
    const bridge = createLiveOperationsBridge({ apiOrigin: 'http://api.test', fetcher })
    bridge.bindRun?.('session-1', 'run-1')

    const projection = await bridge.getProjection?.('session-1')

    expect(projection?.status).toBe('succeeded')
    expect(projection?.artifacts[0]).toMatchObject({
      id: 'artifact-1', name: 'deck.pptx', type: 'presentation', previewAvailable: true,
      previewUri: '/artifacts/artifact-1/preview', downloadUri: '/artifacts/artifact-1/download',
      qualityReportId: 'quality-1', qualityIssues: ['contrast on slide 4'], degraded: true,
      fallbackRenderer: 'presentation.pptx',
      comparison: { previousPreviewUri: '/artifacts/artifact-1/previous-preview', previousRenderer: 'pptx-legacy', previousVersion: '0.9' },
    })

    await bridge.reviewArtifact?.('session-1', projection!.artifacts[0], 'reject', 'contrast remains below threshold')
    const reviewCall = fetcher.mock.calls[fetcher.mock.calls.length - 1]
    const reviewInit = reviewCall?.[1] as RequestInit | undefined
    expect(reviewInit?.method).toBe('POST')
    expect(reviewInit?.headers).toMatchObject({ 'x-operator-id': 'local-operator' })
    expect(JSON.parse(String(reviewInit?.body))).toMatchObject({ task_id: 'task-1', artifact_id: 'artifact-1', decision: 'reject', reason: 'contrast remains below threshold' })
  })

  it('uses the configured operator identity for authenticated reviews', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ run_id: 'run-1', task_id: 'task-1', status: 'running' }), { status: 200 }))
    const bridge = createLiveOperationsBridge({ apiOrigin: 'http://api.test', operatorId: 'reviewer-7', fetcher })
    bridge.bindRun?.('session-1', 'run-1')

    await bridge.reviewArtifact?.('session-1', { id: 'artifact-1' } as never, 'approve')

    const reviewInit = fetcher.mock.calls[fetcher.mock.calls.length - 1]?.[1] as RequestInit | undefined
    expect(reviewInit?.headers).toMatchObject({ 'x-operator-id': 'reviewer-7' })
  })

  it('binds the durable run returned by the native MCP tool to the session', () => {
    const bridge = createLiveOperationsBridge({ fetcher: vi.fn() })
    const bindRun = vi.spyOn(bridge, 'bindRun')

    observeHarnessEvent(bridge, 'session-1', {
      type: 'tool/call', data: { callId: 'call-1', name: 'start_sudarshan_run' },
    })
    observeHarnessEvent(bridge, 'session-1', {
      type: 'tool/result', data: {
        message: {
          source: { callId: 'call-1' },
          content: [{ type: 'text', text: JSON.stringify({ run_id: 'run-42', status: 'queued' }) }],
        },
      },
    })

    expect(bindRun).toHaveBeenCalledWith('session-1', 'run-42')
  })

  it('keeps the safe status taxonomy and telemetry projection', async () => {
    const fetcher = vi.fn(async () => new Response(JSON.stringify({
      run_id: 'run-1',
      task_id: 'task-1',
      status: 'cancelled',
      stage: 'cancellation',
      children: [
        { id: 'child-approval', status: 'waiting_for_approval', pipeline: 'publish' },
        { id: 'child-provider', status: 'pending', pipeline: 'video' },
        { id: 'child-retry', status: 'retrying', pipeline: 'brief' },
      ],
      telemetry: {
        queue_wait_ms: 240,
        input_tokens: 100,
        output_tokens: 40,
        reasoning_tokens: 10,
        usage_is_estimate: true,
        cache_hits: 2,
        cache_waits: 1,
        fallback_count: 1,
      },
    }), { status: 200 }))
    const bridge = createLiveOperationsBridge({ fetcher })

    const projection = await bridge.getProjection?.('run-1')

    expect(projection).toMatchObject({
      status: 'cancelled',
      telemetry: {
        queueWaitMs: 240,
        inputTokens: 100,
        outputTokens: 40,
        reasoningTokens: 10,
        usageIsEstimate: true,
        cacheHits: 2,
        cacheWaits: 1,
        fallbackCount: 1,
      },
    })
    expect(projection?.children.map(child => child.status)).toEqual(['approval', 'provider-pending', 'retry'])
  })

  it('reconnects from the latest event cursor without replaying from zero', async () => {
    Object.defineProperty(globalThis, 'sessionStorage', { configurable: true, value: sessionStorageMock })
    const fetcher = vi.fn(async () => new Response(JSON.stringify({ run_id: 'run-1', status: 'running', events: [] }), { status: 200 }))
    const bridge = createLiveOperationsBridge({ fetcher, eventSource: FakeEventSource as unknown as typeof EventSource })

    const dispose = bridge.subscribeProjection?.('session-1', () => undefined)
    const first = FakeEventSource.instances[0]
    expect(first.url).toContain('after_sequence=0')
    vi.useFakeTimers()
    first.emit('progress', JSON.stringify({ sequence: 12 }))
    first.fail()

    await vi.advanceTimersByTimeAsync(1_000)

    const second = FakeEventSource.instances[1]
    expect(second.url).toContain('after_sequence=12')
    dispose?.()
  })
})
