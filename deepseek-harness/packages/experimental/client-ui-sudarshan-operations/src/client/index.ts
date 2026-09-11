/** Sudarshan operator projections: additive Harness details panel + header action. */
import type { Context as ClientContext } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-client-locale/client'
import type {} from '@deepseek-ai/dsh-client-ui-chat/client'
import type {} from '@deepseek-ai/dsh-client-ui-conversation/client'
import type {} from '@deepseek-ai/dsh-client-ui-layout/client'
import type {} from '@deepseek-ai/dsh-client-ui-renderer/client'
import { OperationsAction } from './OperationsAction.tsx'
import { OperationsPanel } from './OperationsPanel.tsx'
import { en, NS, zh } from './locales.ts'
import './contract.ts'

export const inject = ['layout', 'locale', 'slots']

export function apply(ctx: ClientContext): void {
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
