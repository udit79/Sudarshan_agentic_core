import type { SidebarBrandMarkOwnerProps } from '@deepseek-ai/dsh-client-ui-sidebar/client'
import type { HeroBrandMarkOwnerProps } from '@deepseek-ai/dsh-client-ui-conversation/client'

type SudarshanMarkProps = {
  size: number
  className?: string | undefined
}

/**
 * Render the Sudarshan 1.0 mandala mark with the presentation requested by
 * its host surface. The individual rings remain SVG geometry so the mark is
 * crisp in both the expanded sidebar and the collapsed rail.
 * @param props - Host-supplied mark presentation.
 * @returns the animated Sudarshan mark.
 */
function SudarshanMark({ size, className }: SudarshanMarkProps) {
  return (
    <svg
      data-sudarshan-brand-mark="true"
      className={className}
      width={size}
      height={size}
      viewBox="0 0 40 40"
      fill="none"
      aria-hidden="true"
    >
      <circle className="sudarshan-brand-orbit" cx="20" cy="20" r="18" stroke="#8b5cf6" strokeWidth="1.5" strokeDasharray="3 2" opacity="0.9" />
      <circle className="sudarshan-brand-ring" cx="20" cy="20" r="12" stroke="#60a5fa" strokeWidth="1.5" />
      <path className="sudarshan-brand-rays" d="M20 4V36M4 20H36M8.7 8.7L31.3 31.3M8.7 31.3L31.3 8.7" stroke="#c084fc" strokeWidth="1.2" />
      <circle className="sudarshan-brand-core-glow" cx="20" cy="20" r="7" fill="#6366f1" opacity="0.18" />
      <circle className="sudarshan-brand-core" cx="20" cy="20" r="4" fill="#38bdf8" />
    </svg>
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
