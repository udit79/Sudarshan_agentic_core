/** Sudarshan operator projections: additive Harness details panel + header action. */
import type { Context as ClientContext } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-client-locale/client'
import type {} from '@deepseek-ai/dsh-client-ui-chat/client'
import type {} from '@deepseek-ai/dsh-client-ui-conversation/client'
import type {} from '@deepseek-ai/dsh-client-ui-layout/client'
import type {} from '@deepseek-ai/dsh-client-ui-renderer/client'
import type {} from '@deepseek-ai/dsh-client-ui-session/client'
import type { ISessions, SessionEventLikeEntry } from '@deepseek-ai/dsh-api-session-controller/client'
import { OperationsAction } from './OperationsAction.tsx'
import { OperationsPanel } from './OperationsPanel.tsx'
import { installLiveOperationsBridge, observeHarnessEvent } from './live-bridge.ts'
import { en, NS, zh } from './locales.ts'
import './contract.ts'

export const inject = ['layout', 'locale', 'sessions', 'slots']

export function apply(ctx: ClientContext): void {
  const bridge = installLiveOperationsBridge()
  ctx.effect(() => {
    const sessions = ctx.sessions as ISessions
    type SessionId = Parameters<ISessions['binding']>[0]
    const observed = new Map<string, { revision: number; dispose: () => void }>()
    const observe = (sessionId: SessionId): void => {
      const key = String(sessionId)
      if (observed.has(key)) return
      const binding = sessions.binding(sessionId)
      if (!binding) return
      const source = binding.eventSource
      const consume = (entries: readonly SessionEventLikeEntry[]): void => {
        for (const entry of entries) {
          if (entry.type === 'event') observeHarnessEvent(bridge, key, entry.event)
        }
      }
      const initial = source.getSnapshot()
      const state: { revision: number; dispose: () => void } = {
        revision: initial.revision,
        dispose: () => undefined,
      }
      state.dispose = source.subscribe(() => {
        const next = source.getSnapshot()
        if (next.revision === state.revision) return
        state.revision = next.revision
        consume(next.change.kind === 'append' ? next.change.entries : next.entries)
      })
      observed.set(key, state)
    }
    const sync = (): void => {
      const snapshot = sessions.list.getSnapshot()
      for (const sessionId of snapshot.ids) observe(sessionId)
      if (snapshot.current) observe(snapshot.current)
    }
    sync()
    const disposeList = sessions.list.subscribe(sync)
    return () => {
      disposeList()
      for (const state of observed.values()) state.dispose()
      observed.clear()
    }
  }, 'sudarshan-operations: native run binding')
  ctx.effect(() => ctx.locale.register(NS, { zh, en }), 'sudarshan-operations: dictionaries')
  ctx.slots.inject('conversation.details.operations', () => ctx.slots.register({
    name: 'conversation.details.operations',
    id: 'sudarshan-operations-panel',
    locale: NS,
  }, OperationsPanel))
  ctx.slots.inject('conversation.session.header.utilities', () => ctx.slots.register({
    name: 'conversation.session.header.utilities',
    id: 'sudarshan-operations-action',
    order: 40,
    locale: NS,
    inject: () => ({ openOperations: () => { ctx.layout.openDetails() } }),
  }, OperationsAction))
}
