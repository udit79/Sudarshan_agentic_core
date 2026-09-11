/** Copy owned by the Sudarshan operator-projection plugin. */
export const NS = 'sudarshanOperations'

export const zh = {
  'action.label': 'Sudarshan 运维',
  'action.aria': '打开 Sudarshan 运维面板',
  'title': 'Sudarshan 运维',
  'fixture': '预览投影 · 尚未连接后端',
  'session': '会话范围',
  'monitor': '执行监视',
  'evidence': '证据',
  'artifacts': '产物',
  'ingestion': '摄取',
  'refresh': '刷新投影',
  'safeProjection': '仅显示安全投影；原始提示词、记忆和隐藏推理不会进入 UI。',
} as const

export const en: Record<OperationKey, string> = {
  'action.label': 'Sudarshan ops',
  'action.aria': 'Open Sudarshan operations panel',
  'title': 'Sudarshan operations',
  'fixture': 'Preview projection · backend not connected',
  'session': 'Session-scoped',
  'monitor': 'Execution',
  'evidence': 'Evidence',
  'artifacts': 'Artifacts',
  'ingestion': 'Ingestion',
  'refresh': 'Refresh projection',
  'safeProjection': 'Safe projection only; raw prompts, memory, and hidden reasoning never enter the UI.',
}

export type OperationKey = keyof typeof zh
