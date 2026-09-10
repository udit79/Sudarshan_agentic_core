import { BrandWordmark, FishLogo } from '@deepseek-ai/dsh-client-ui-primitives'
import type { SidebarBrandMarkOwnerProps } from '@deepseek-ai/dsh-client-ui-sidebar/client'

/** Render the mark in the expanded sidebar and collapsed rail. */
export function OfficialBrandMark({ size }: SidebarBrandMarkOwnerProps) {
  return <FishLogo size={size} />
}

/**
 * Render the Sudarshan 1.0 wordmark and AI tag without its independently
 * slotted mark.
 * @returns the Sudarshan name artwork.
 */
export function OfficialBrandName() {
  return <BrandWordmark includeMark={false} />
}
