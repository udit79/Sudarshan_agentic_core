import { useEffect, useState } from 'react'
import type { OperationKey } from './locales.ts'
import { getOperationsBridge, previewProjection, type ArtifactProjection, type OperationsBridge, type OperatorProjection, type ProjectionStatus } from './projection.ts'
import css from './OperationsPanel.module.css'

type Tab = 'monitor' | 'evidence' | 'artifacts' | 'ingestion'
type PanelProps = { sessionId: string; t: (key: OperationKey) => string }

const TABS: readonly { id: Tab; label: OperationKey }[] = [
  { id: 'monitor', label: 'monitor' },
  { id: 'evidence', label: 'evidence' },
  { id: 'artifacts', label: 'artifacts' },
  { id: 'ingestion', label: 'ingestion' },
]

function storageKey(sessionId: string): string { return `sudarshan.operations.tab.${sessionId}` }

function readTab(sessionId: string): Tab {
  try {
    const value = sessionStorage.getItem(storageKey(sessionId))
    return TABS.some(tab => tab.id === value) ? value as Tab : 'monitor'
  } catch { return 'monitor' }
}

function Status({ status }: { status: ProjectionStatus | ArtifactProjection['status'] }) {
  const label = status.replace('-', ' ')
  return <span className={css.status}><span className={css.dot} data-status={status} />{label}</span>
}

function Progress({ value }: { value: number }) {
  return <div className={css.progress} aria-label={`${value}% complete`}><span style={{ width: `${value}%` }} /></div>
}

function Monitor({ projection }: { projection: OperatorProjection }) {
  return <>
    <div className={css.hero}>
      <div className={css.heroRow}><div><div className={css.heroLabel}>Parent run</div><div className={css.heroValue}>{projection.stage}</div></div><Status status={projection.status} /></div>
      <Progress value={projection.progress} />
      <div className={css.chipRow}><span className={css.chip}>{projection.runId}</span><span className={css.chip}>{projection.queue}</span></div>
      <div className={css.detail}>{projection.waitReason}</div>
    </div>
    <div className={css.sectionTitle}>Child lanes</div>
    <div>{projection.children.map(child => <div key={child.id} className={css.lane}>
      <div className={css.laneTop}><span className={css.name}>{child.label}</span><Status status={child.status} /></div>
      <div className={css.detail}>{child.pipeline}{child.waitReason ? ` · ${child.waitReason}` : ''}</div>
      <div className={css.miniProgress}><span style={{ width: `${child.progress}%` }} /></div>
    </div>)}</div>
    <div className={css.muted}>Refresh/reconnect keeps the run and task IDs stable; the backend will supply the SSE cursor and authoritative state.</div>
  </>
}

function Evidence({ projection }: { projection: OperatorProjection }) {
  return <>
    <div className={css.muted}>Authorized references only. Retrieved text, prompts, memory payloads, and hidden reasoning stay out of the drawer.</div>
    {projection.evidence.map(item => <div key={item.id} className={css.row}>
      <div className={css.rowTop}><span className={css.evidenceId}>{item.id}</span><span className={css.chip}>{item.classification}</span></div>
      <div className={css.name}>{item.sourceReference}</div>
      <div className={css.detail}>{item.location} · confidence {item.confidence}</div>
      <div className={css.detail}>{item.provenance}</div>
    </div>)}
  </>
}

function artifactLabel(type: ArtifactProjection['type']): string {
  return ({ markdown: 'MD', presentation: 'PPT', infographic: 'SVG', video: 'MP4', linkedin: 'IN' })[type]
}

function Artifacts({ projection, bridge }: { projection: OperatorProjection; bridge: OperationsBridge | undefined }) {
  return <>
    <div className={css.muted}>{bridge ? 'Artifacts are controlled by the authenticated Sudarshan adapter.' : 'Preview fixture: connect the Sudarshan adapter to enable artifact actions.'}</div>
    {projection.artifacts.map(artifact => <div key={artifact.id} className={css.card}>
      <div className={css.cardTop}><div className={css.artifactInfo}><span className={css.artifactIcon}>{artifactLabel(artifact.type)}</span><span className={`${css.name} ${css.artifactName}`}>{artifact.name}</span></div><Status status={artifact.status} /></div>
      <div className={css.detail}>{artifact.renderer} v{artifact.version} · {artifact.size} · {artifact.classification}</div>
      {artifact.repair && <div className={css.repair}>{artifact.repair}</div>}
      <div className={css.actionRow}><button className={css.button} type="button" disabled={!artifact.previewAvailable || !bridge?.previewArtifact} onClick={() => { bridge?.previewArtifact?.(artifact) }}>Preview</button><button className={`${css.button} ${css.buttonSecondary}`} type="button" disabled={!artifact.previewAvailable || !bridge?.downloadArtifact} onClick={() => { bridge?.downloadArtifact?.(artifact) }}>Open / download</button></div>
    </div>)}
  </>
}

function Ingestion({ projection, sessionId, bridge }: { projection: OperatorProjection; sessionId: string; bridge: OperationsBridge | undefined }) {
  return <>
    <div className={css.muted}>Upload and ingestion stay receipt-driven. Large files use multipart upload; extracted content is never rendered as raw chat text.</div>
    {projection.ingestionStages.map(stage => <div key={stage.label} className={css.row}><div className={css.rowTop}><span className={css.name}>{stage.label}</span><Status status={stage.status} /></div><div className={css.detail}>{stage.detail}</div></div>)}
    <div className={css.actionRow}><button className={css.button} type="button" disabled={!bridge?.retryIngestion} onClick={() => { bridge?.retryIngestion?.(sessionId) }}>Retry failed stage</button><button className={`${css.button} ${css.buttonSecondary}`} type="button" disabled={!bridge?.cancelIngestion} onClick={() => { bridge?.cancelIngestion?.(sessionId) }}>Cancel ingestion</button></div>
  </>
}

export function OperationsPanel({ sessionId, t }: PanelProps) {
  const [tab, setTab] = useState<Tab>(() => readTab(sessionId))
  const [refresh, setRefresh] = useState(0)
  const [projection, setProjection] = useState<OperatorProjection>(() => previewProjection(sessionId))
  const [bridge, setBridge] = useState<OperationsBridge | undefined>(() => getOperationsBridge())

  useEffect(() => {
    const currentBridge = getOperationsBridge()
    setBridge(currentBridge)
    if (!currentBridge?.getProjection) {
      setProjection(previewProjection(sessionId, refresh))
      return
    }
    let active = true
    Promise.resolve(currentBridge.getProjection(sessionId)).then(value => {
      if (active) setProjection(value)
    }).catch(() => {
      if (active) setProjection(previewProjection(sessionId, refresh))
    })
    return () => { active = false }
  }, [refresh, sessionId])

  useEffect(() => {
    try { sessionStorage.setItem(storageKey(sessionId), tab) } catch { /* session storage is optional */ }
  }, [sessionId, tab])

  return <div className={css.root} data-sudarshan-operations>
    <div className={css.heading}><div className={css.eyebrow}>Sudarshan AI · operator console</div><div className={css.title}>{t('title')}</div><div className={css.meta}>{t('session')} · {projection.runId}</div><div className={css.fixture}>{t('fixture')}<br />{t('safeProjection')}</div></div>
    <div className={css.tabs} role="tablist" aria-label={t('title')}>
      {TABS.map(item => <button key={item.id} type="button" role="tab" aria-selected={tab === item.id} className={`${css.tab} ${tab === item.id ? css.tabActive : ''}`} onClick={() => { setTab(item.id) }}>{t(item.label)}</button>)}
    </div>
    <div className={css.body} role="tabpanel">
      <div className={css.toolbar}><span>{projection.status} · synced {projection.generatedAt}</span><button className={css.refresh} type="button" onClick={() => { setRefresh((value: number) => value + 1) }}>{t('refresh')}</button></div>
      {tab === 'monitor' && <Monitor projection={projection} />}
      {tab === 'evidence' && <Evidence projection={projection} />}
      {tab === 'artifacts' && <Artifacts projection={projection} bridge={bridge} />}
      {tab === 'ingestion' && <Ingestion projection={projection} sessionId={sessionId} bridge={bridge} />}
    </div>
  </div>
}
