import type { SidebarBrandMarkOwnerProps } from '@deepseek-ai/dsh-client-ui-sidebar/client'
import type { HeroBrandMarkOwnerProps } from '@deepseek-ai/dsh-client-ui-conversation/client'

type SudarshanMarkProps = {
  size: number
  className?: string | undefined
}

/**
 * Render the supplied landing-page S mark in the host brand slots.
 * @param props - Host-supplied mark presentation.
 * @returns the animated Sudarshan mark.
 */
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
export function OfficialBrandMark({ size }: SidebarBrandMarkOwnerProps) {
  return <SudarshanMark size={size} />
}

/** Render the same mark in the empty-session hero slot. */
export function OfficialHeroBrandMark({ size, className }: HeroBrandMarkOwnerProps) {
  return <SudarshanMark size={size} className={className} />
}

/**
 * Render the Sudarshan 1.0 wordmark and AI tag without its independently
 * slotted mark.
 * @returns the Sudarshan name artwork.
 */
export function OfficialBrandName() {
  return <>
    <span className="sudarshan-brand-name">Sudarshan</span>
    <span className="sudarshan-brand-tag">AI</span>
  </>
}
