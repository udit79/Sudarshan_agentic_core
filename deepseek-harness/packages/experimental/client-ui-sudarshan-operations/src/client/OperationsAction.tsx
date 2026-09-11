import css from './OperationsAction.module.css'

export type OperationsActionProps = { openOperations: () => void; t: (key: string) => string }

export function OperationsAction({ openOperations, t }: OperationsActionProps) {
  return <button type="button" className={css.button} aria-label={t('action.aria')} title={t('action.label')} onClick={() => { openOperations() }}>
    <span className={css.dot} aria-hidden />
    <span>{t('action.label')}</span>
  </button>
}
