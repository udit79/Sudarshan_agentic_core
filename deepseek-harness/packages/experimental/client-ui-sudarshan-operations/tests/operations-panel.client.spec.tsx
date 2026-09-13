// @vitest-environment jsdom
import { fireEvent, render, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { cleanup } from '@testing-library/react'
import { OperationsPanel } from '../src/client/OperationsPanel.tsx'
import type { ArtifactProjection } from '../src/client/projection.ts'

afterEach(() => {
  cleanup()
  delete globalThis.SudarshanOperationsBridge
})

describe('Sudarshan operations panel', () => {
  it('keeps safe projection tabs session-scoped and renders artifact metadata', () => {
    const view = render(<OperationsPanel sessionId="session-test" t={(key) => key} />)
    expect(view.getByText('run-preview-n-test')).toBeTruthy()
    expect(view.queryByRole('tab', { name: 'approvals' })).toBeNull()
    expect(view.queryByRole('tab', { name: 'operations' })).toBeNull()
    fireEvent.click(view.getByRole('tab', { name: 'artifacts' }))
    expect(view.getByText('board-deck.pptx')).toBeTruthy()
    expect(view.getByText('1 slide needs contrast review')).toBeTruthy()
    expect(view.getByText('comparePreview')).toBeTruthy()
    expect(view.getAllByText('qualityIssues').length).toBe(2)
    expect(view.getAllByText(/degraded/).length).toBe(2)
    expect(view.getAllByText('Missing source label on 1 chart').length).toBe(2)
  })

  it('requires a rejection reason and forwards an auditable artifact decision', async () => {
    const reviewArtifact = vi.fn((_sessionId: string, _artifact: ArtifactProjection, _decision: 'approve' | 'reject', _reason?: string) => undefined)
    globalThis.SudarshanOperationsBridge = { reviewArtifact }
    const view = render(<OperationsPanel sessionId="session-review" t={(key) => key} />)

    fireEvent.click(view.getByRole('tab', { name: 'artifacts' }))
    const reviewButtons = await view.findAllByRole('button', { name: 'review' })
    fireEvent.click(reviewButtons[0])
    expect(view.getByRole('dialog')).toBeTruthy()

    fireEvent.click(view.getByRole('button', { name: 'rejectArtifact' }))
    expect(view.getByRole('alert').textContent).toBe('reasonRequired')

    fireEvent.change(view.getByRole('textbox'), { target: { value: 'contrast remains below threshold' } })
    fireEvent.click(view.getByRole('button', { name: 'rejectArtifact' }))
    await waitFor(() => expect(reviewArtifact).toHaveBeenCalledWith('session-review', expect.objectContaining({ id: 'art-deck' }), 'reject', 'contrast remains below threshold'))
    expect(view.queryByRole('dialog')).toBeNull()
  })
})
