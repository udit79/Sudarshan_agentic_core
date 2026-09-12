import { useCallback, useRef, useState } from 'react'
import type { ChangeEvent, DragEvent } from 'react'
import type { SessionId } from '@deepseek-ai/dsh-session/types'
import type {} from '@deepseek-ai/dsh-client-ui-session/client'
import type { HeroCaseDocumentsOwnerProps } from '@deepseek-ai/dsh-client-ui-conversation/client'
import css from './CaseDocumentDrop.module.css'

/** File types accepted by the Sudarshan document/RAG ingestion boundary. */
export const SUPPORTED_CASE_DOCUMENT_EXTENSIONS = [
  '.txt', '.pdf', '.pptx', '.pptm', '.ppsx', '.ppsm', '.potx', '.potm',
] as const

const ACCEPT = SUPPORTED_CASE_DOCUMENT_EXTENSIONS.join(',')

type UploadState =
  | { kind: 'idle'; message: string }
  | { kind: 'uploading'; message: string }
  | { kind: 'success'; message: string }
  | { kind: 'error'; message: string }

function apiOrigin(): string {
  const configured = (globalThis as typeof globalThis & { SUDARSHAN_API_ORIGIN?: string }).SUDARSHAN_API_ORIGIN
  return (configured ?? 'http://localhost:8000').replace(/\/$/, '')
}

function operatorId(): string {
  return (globalThis as typeof globalThis & { SUDARSHAN_OPERATOR_ID?: string }).SUDARSHAN_OPERATOR_ID
    ?? 'local-operator'
}

function supported(file: File): boolean {
  const name = file.name.toLowerCase()
  return SUPPORTED_CASE_DOCUMENT_EXTENSIONS.some(extension => name.endsWith(extension))
}

function caseId(sessionId: SessionId): string {
  return `case-${String(sessionId)}`
}

/** Case-scoped RAG document intake. Uploads use the governed /ingest boundary. */
export function CaseDocumentDrop({ sessionId, createSession }: HeroCaseDocumentsOwnerProps & { sessionId?: SessionId }) {
  const inputRef = useRef<HTMLInputElement | null>(null)
  const [dragActive, setDragActive] = useState(false)
  const [state, setState] = useState<UploadState>({
    kind: 'idle',
    message: 'Drop supported documents to add case evidence',
  })

  const upload = useCallback(async (files: readonly File[]) => {
    const accepted = files.filter(supported)
    const rejected = files.length - accepted.length
    if (accepted.length === 0) {
      setState({ kind: 'error', message: 'Supported: TXT, PDF, and PowerPoint files' })
      return
    }
    setState({ kind: 'uploading', message: `Indexing ${accepted.length} document${accepted.length === 1 ? '' : 's'}…` })
    let completed = 0
    try {
      const activeSessionId = sessionId ?? await createSession()
      for (const file of accepted) {
        const form = new FormData()
        form.append('file', file, file.name)
        form.append('user_id', operatorId())
        form.append('case_id', caseId(activeSessionId))
        form.append('task_id', caseId(activeSessionId))
        form.append('classification_level', 'RESTRICTED')
        const response = await fetch(`${apiOrigin()}/ingest`, {
          method: 'POST',
          headers: {
            'x-operator-id': operatorId(),
            'x-case-id': caseId(activeSessionId),
            'x-classification-level': 'RESTRICTED',
            'Idempotency-Key': `${String(activeSessionId)}:${file.name}:${file.size}:${file.lastModified}`,
          },
          body: form,
        })
        if (!response.ok) {
          const detail = await response.text()
          throw new Error(detail || `HTTP ${response.status}`)
        }
        completed += 1
      }
      const suffix = rejected > 0 ? ` ${rejected} unsupported file${rejected === 1 ? '' : 's'} skipped.` : ''
      setState({ kind: 'success', message: `${completed} document${completed === 1 ? '' : 's'} added to this case.${suffix}` })
    } catch (error) {
      setState({ kind: 'error', message: `Document indexing failed: ${error instanceof Error ? error.message : String(error)}` })
    }
  }, [createSession, sessionId])

  const onFiles = useCallback((event: ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(event.currentTarget.files ?? [])
    event.currentTarget.value = ''
    if (files.length > 0) void upload(files)
  }, [upload])

  const onDrop = useCallback((event: DragEvent<HTMLDivElement>) => {
    event.preventDefault()
    setDragActive(false)
    const files = Array.from(event.dataTransfer.files)
    if (files.length > 0) void upload(files)
  }, [upload])

  return (
    <div
      className={`${css.root} ${dragActive ? css.active : ''}`}
      data-case-document-drop="true"
      onDragEnter={(event) => { event.preventDefault(); setDragActive(true) }}
      onDragOver={(event) => { event.preventDefault(); event.dataTransfer.dropEffect = 'copy' }}
      onDragLeave={() => { setDragActive(false) }}
      onDrop={onDrop}
    >
      <input ref={inputRef} type="file" accept={ACCEPT} multiple hidden onChange={onFiles} />
      <span className={css.icon} aria-hidden="true">RAG</span>
      <span className={css.copy}>
        <strong>Case evidence</strong>
        <span>{state.message}</span>
      </span>
      <button type="button" className={css.button} onClick={() => { inputRef.current?.click() }} disabled={state.kind === 'uploading'}>
        {state.kind === 'uploading' ? 'Indexing…' : 'Add documents'}
      </button>
    </div>
  )
}
