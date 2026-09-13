// @vitest-environment jsdom
import { Context } from '@deepseek-ai/cordis'
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup, render } from '@testing-library/react'
import { SlotRegistry } from '@deepseek-ai/dsh-client-ui-renderer/client'
import { apply, inject } from '../src/client/index.ts'
import { SudarshanBrandMark, SudarshanBrandName, SudarshanHeroBrandMark } from '../src/client/Brand.tsx'

afterEach(() => cleanup())

const HOLES = [
  'sidebar.brand.mark',
  'sidebar.brand.name',
  'conversation.hero.brand.mark',
] as const

async function bench() {
  const ctx = new Context()
  await ctx.plugin(SlotRegistry).await()
  const slots = ctx.get('slots') as SlotRegistry
  slots.register({
    name: 'root',
    children: Object.fromEntries(HOLES.map(name => [name, { kind: 'single', scope: 'root' }])),
  } as never, () => null)
  return { ctx, slots }
}

describe('Sudarshan browser-brand plugin', () => {
  it('declares only the slot service it uses', () => {
    expect(inject).toEqual(['slots'])
  })

  it('fills and disposes every shared brand slot', async () => {
    const subject = await bench()
    const fiber = subject.ctx.plugin({ inject: [...inject], apply })
    await fiber.await()
    for (const hole of HOLES) expect(subject.slots.entries(hole)).toHaveLength(1)
    await fiber.dispose()
    for (const hole of HOLES) expect(subject.slots.entries(hole)).toHaveLength(0)
  })

  it('renders the wordmark, sidebar mark, and hero mark independently', () => {
    const name = render(<SudarshanBrandName />)
    expect(name.container.textContent).toBe('SudarshanAI')
    name.unmount()

    const mark = render(<SudarshanBrandMark size={34} />)
    expect(mark.container.querySelector('img')?.getAttribute('width')).toBe('34')
    expect(mark.container.querySelector('img')?.getAttribute('src')).toBe('/assets/sudarshan-icon.png')
    const hero = render(<SudarshanHeroBrandMark size={28} className="hero-mark" />)
    expect(hero.container.querySelector('[data-sudarshan-brand-mark]')?.getAttribute('class')).toBe('hero-mark')
  })
})
