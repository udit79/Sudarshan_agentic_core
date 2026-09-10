/** Product-owned theme stylesheet with a lifecycle tied to the plugin fiber. */
import type { Context } from '@deepseek-ai/cordis'
import styles from '../styles/sudarshan.css?inline'

const PLUGIN_ID = '@deepseek-ai/dsh-experimental-client-ui-sudarshan-theme'

/** This plugin has no Cordis service prerequisites. */
export const inject: readonly string[] = []

/** Mount and remove the theme as one owned stylesheet. */
export function apply(ctx: Context): void {
  if (typeof document === 'undefined') return
  ctx.effect(() => {
    const tag = document.createElement('style')
    tag.dataset.plugin = PLUGIN_ID
    tag.dataset.pluginCss = `${PLUGIN_ID}/sudarshan.css`
    tag.textContent = styles
    document.head.appendChild(tag)
    return () => { tag.remove() }
  }, 'sudarshan-theme: stylesheet')
}
