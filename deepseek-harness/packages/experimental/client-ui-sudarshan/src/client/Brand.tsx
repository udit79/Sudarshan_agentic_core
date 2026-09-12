import type { SidebarBrandMarkOwnerProps } from '@deepseek-ai/dsh-client-ui-sidebar/client'
import type { HeroBrandMarkOwnerProps } from '@deepseek-ai/dsh-client-ui-conversation/client'

type SudarshanMarkProps = {
  size: number
  className?: string | undefined
}

/** Render the supplied landing-page S mark in every compact brand slot. */
function SudarshanMark({ size, className }: SudarshanMarkProps) {
  return (
    <img
      data-sudarshan-brand-mark="true"
      className={className}
      src="/assets/sudarshan-icon.png"
      width={size}
      height={size}
      alt=""
      aria-hidden="true"
    />
  )
}

/** Render the mark in the expanded sidebar and collapsed rail. */
export function SudarshanBrandMark({ size }: SidebarBrandMarkOwnerProps) {
  return <SudarshanMark size={size} />
}

/** Render the mark in the empty-session hero slot. */
export function SudarshanHeroBrandMark({ size, className }: HeroBrandMarkOwnerProps) {
  return <SudarshanMark size={size} className={className} />
}

/** Render the wordmark without duplicating the independently slotted mark. */
export function SudarshanBrandName() {
  return <>
    <span className="sudarshan-brand-name">Sudarshan</span>
    <span className="sudarshan-brand-tag">AI</span>
  </>
}
