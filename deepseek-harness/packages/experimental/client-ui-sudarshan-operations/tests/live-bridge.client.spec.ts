import { describe, expect, it, vi } from 'vitest'
import { createLiveOperationsBridge, observeHarnessEvent } from '../src/client/live-bridge.ts'

describe('Sudarshan live operations bridge', () => {
  it('hydrates terminal pipeline manifests through stable artifact routes', async () => {
    const fetcher = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input)
      if (url.endsWith('/runs/run-1')) {
        return new Response(JSON.stringify({ run_id: 'run-1', task_id: 'task-1', status: 'completed', pipeline: 'ppt', pipelines: ['ppt'] }), { status: 200 })
      }
      expect(url).toContain('/artifacts/run-1/presentation/manifest')
      return new Response(JSON.stringify({
        artifact_id: 'artifact-1', kind: 'presentation', name: 'deck.pptx',
        preview_uri: '/artifacts/artifact-1/preview', uri: '/artifacts/artifact-1/download',
        renderer_version: 'pptx-native@1', size_bytes: 1024, classification_level: 'RESTRICTED',
        quality_status: 'passed',
      }), { status: 200 })
    })
    const bridge = createLiveOperationsBridge({ apiOrigin: 'http://api.test', fetcher })

    const projection = await bridge.getProjection?.('run-1')

    expect(projection?.status).toBe('succeeded')
    expect(projection?.artifacts[0]).toMatchObject({
      id: 'artifact-1', name: 'deck.pptx', type: 'presentation', previewAvailable: true,
      previewUri: '/artifacts/artifact-1/preview', downloadUri: '/artifacts/artifact-1/download',
    })
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
})
