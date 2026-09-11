// @vitest-environment jsdom
import { fireEvent, render } from '@testing-library/react'
import { afterEach, describe, expect, it } from 'vitest'
import { cleanup } from '@testing-library/react'
import { OperationsPanel } from '../src/client/OperationsPanel.tsx'

afterEach(() => cleanup())

describe('Sudarshan operations panel', () => {
  it('keeps safe projection tabs session-scoped and renders artifact metadata', () => {
    const view = render(<OperationsPanel sessionId="session-test" t={(key) => key} />)
    expect(view.getByText('run-preview-n-test')).toBeTruthy()
    expect(view.queryByRole('tab', { name: 'approvals' })).toBeNull()
    expect(view.queryByRole('tab', { name: 'operations' })).toBeNull()
    fireEvent.click(view.getByRole('tab', { name: 'artifacts' }))
    expect(view.getByText('board-deck.pptx')).toBeTruthy()
    expect(view.getByText('1 slide needs contrast review')).toBeTruthy()
  })
})
