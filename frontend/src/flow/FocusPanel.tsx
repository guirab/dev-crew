import type { StageKey } from '../contracts/aliases'
import type { LogLine, TaskView } from '../contracts/generated'
import b from '../bodies/body.module.css'
import { cx } from '../lib/cx'
import { EpicsSection } from './EpicsSection'
import type { RailStep } from './rail'
import { StageBody } from './StageBody'
import { FOCUS_PANEL_ID } from './StageRail'
import { stageDescription, withProgress } from './stages'
import styles from './FocusPanel.module.css'

function TaskSummary({ view }: { view: TaskView }) {
  return (
    <>
      <div className={b.sec}>
        <h4>Tarefa</h4>
        <b>{view.title}</b>
        {view.description && (
          <p className={b.muted} style={{ margin: '4px 0 0' }}>
            {view.description}
          </p>
        )}
      </div>
      <div className={cx(b.sec, b.muted)}>Repo: {view.repo}</div>
    </>
  )
}

interface FocusPanelProps {
  view: TaskView
  step: RailStep
  progress: Partial<Record<StageKey, LogLine[]>>
}

/** Detalhes da etapa escolhida no trilho: o corpo do estágio, os épicos ou o resumo da tarefa. */
export function FocusPanel({ view, step, progress }: FocusPanelProps) {
  const key = step.key
  let description: string | null = null
  let body
  if (key === 'epics') {
    body = <EpicsSection view={view} />
  } else if (key === 'manual') {
    body = <TaskSummary view={view} />
  } else {
    const stage = withProgress(view.stages[key], progress[key])
    description = stageDescription(key, stage)
    // key: trocar de etapa remonta o corpo (rascunhos não vazam de um estágio pro outro)
    body = <StageBody key={key} stageKey={key} view={view} stage={stage} />
  }

  // épicos: a seção tem cabeçalho próprio e o que precisa de você vira Alert, não o painel inteiro aceso
  const epics = key === 'epics'
  return (
    <section
      role="tabpanel"
      id={FOCUS_PANEL_ID}
      aria-labelledby={`step-${key}`}
      className={cx(styles.panel, !epics && styles[step.status])}
      data-focus={key}
    >
      {!epics && (
        <div className={styles.head}>
          <h2 className={styles.title}>{step.title}</h2>
          {step.tag && <span className={styles.tag}>{step.tag}</span>}
          {description && <p className={styles.desc}>{description}</p>}
        </div>
      )}
      {body}
    </section>
  )
}
