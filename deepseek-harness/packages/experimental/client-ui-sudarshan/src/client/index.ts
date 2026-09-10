/** Sudarshan occupants for the generic browser-brand slots. */
import type { Context as ClientContext } from '@deepseek-ai/cordis'
import type {} from '@deepseek-ai/dsh-client-ui-conversation/client'
import type {} from '@deepseek-ai/dsh-client-ui-renderer/client'
import type {} from '@deepseek-ai/dsh-client-ui-sidebar/client'
import { SudarshanBrandMark, SudarshanBrandName, SudarshanHeroBrandMark } from './Brand.tsx'

/** Required service: the UI slot registry. */
export const inject = ['slots']

/** Fill all brand slots as one declaration-aware registration set. */
export function apply(ctx: ClientContext): void {
  ctx.slots.inject('sidebar.brand.mark', () =>
    ctx.slots.inject('sidebar.brand.name', () =>
      ctx.slots.inject('conversation.hero.brand.mark', function* () {
        yield ctx.slots.register({ name: 'sidebar.brand.mark' }, SudarshanBrandMark)
        yield ctx.slots.register({ name: 'sidebar.brand.name' }, SudarshanBrandName)
        yield ctx.slots.register({ name: 'conversation.hero.brand.mark' }, SudarshanHeroBrandMark)
      })))
}
