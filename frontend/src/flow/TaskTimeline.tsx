import { useId, useState } from 'react'
import type { ReactNode } from 'react'
import type { StageKey } from '../contracts/aliases'
import type { LogLine, Stages, TaskView } from '../contracts/generated'
import { ActivityLog } from '../bodies/ActivityLog'
import { ApprovalBody } from '../bodies/ApprovalBody'
import { DeveloperBody } from '../bodies/DeveloperBody'
import { EscalationPanel } from '../bodies/EscalationPanel'
import { InterviewBody } from '../bodies/InterviewBody'
import { PlannerBody } from '../bodies/PlannerBody'
import { ReviewerBody } from '../bodies/ReviewerBody'
import { TesterBody } from '../bodies/TesterBody'
import { DoneBody } from '../bodies/DoneBody'
import { cx } from '../lib/cx'
import { Button } from '../ui/Button'
import { useCrewStore } from '../store/crew'
import { Escalation } from './Escalation'
import { ExecutionEpics, NextBatch } from './ExecutionEpics'
import { laneView } from './lanes'
import { LimitBanner } from './LimitBanner'
import { withProgress } from './stages'
import { failedStage, isSplit, opensByDefault, reviewLane, timelineNodes } from './timeline'
import type { NodeKey, NodeTone, TimelineNode } from './timeline'
import styles from './Timeline.module.css'

/** Card do nó aberto: âmbar na sua vez, vermelho na falha, verde no resultado. */
const CARD: Partial<Record<NodeTone, string | undefined>> = {
  you: styles.wait,
  pause: styles.wait,
  err: styles.err,
}

/** Sobrepõe as linhas de progresso do WS ao estágio ativo de cada agente. */
function liveStages(stages: Stages, progress: Partial<Record<StageKey, LogLine[]>>): Stages {
  const live = (key: StageKey) => withProgress(stages[key], progress[key])
  return {
    manual: live('manual'),
    interviewer: live('interviewer'),
    planner: live('planner'),
    approval: live('approval'),
    developer: live('developer'),
    tester: live('tester'),
    reviewer: live('reviewer'),
    done: live('done'),
  }
}

/** Escalada de um estágio fora da Execução (Entrevistador, Planner): o painel de decisão no nó dele. */
function StageEscalation({ view, stages }: { view: TaskView; stages: readonly StageKey[] }) {
  const esc = view.escalation
  if (!esc || esc.epic_id || !stages.includes(esc.stage)) return null
  return <EscalationPanel reason={esc.reason} />
}

/** Resultado: a mensagem de commit e os atalhos pra Alterações e pra próxima tarefa. */
function ResultBody({ view }: { view: TaskView }) {
  const setScreen = useCrewStore((s) => s.setScreen)
  return (
    <>
      <DoneBody view={view} stage={view.stages.done} />
      {view.final && (
        <div className={styles.acts}>
          <Button
            onClick={() => {
              setScreen('changes')
            }}
          >
            Ver alterações
          </Button>
          <span className={styles.sp} />
          <Button
            variant="primary"
            onClick={() => {
              setScreen('new')
            }}
          >
            Nova tarefa
          </Button>
        </div>
      )}
    </>
  )
}

function NodeBody({ node, view }: { node: TimelineNode; view: TaskView }) {
  const { stages } = view
  switch (node.key) {
    case 'task':
      return (
        <>
          {view.description && <p>{view.description}</p>}
          <p className={styles.hint}>Repositório: {view.repo}</p>
        </>
      )
    case 'interview':
      return (
        <>
          <StageEscalation view={view} stages={['interviewer']} />
          <InterviewBody view={view} stage={stages.interviewer} />
        </>
      )
    case 'plan':
      return (
        <>
          <StageEscalation view={view} stages={['planner']} />
          {stages.approval.status === 'idle' ? (
            <PlannerBody view={view} stage={stages.planner} />
          ) : (
            <ApprovalBody view={view} stage={stages.approval} />
          )}
        </>
      )
    case 'execution': {
      if (isSplit(view)) return <ExecutionEpics view={view} />
      const esc = view.escalation
      const local = esc && (esc.stage === 'developer' || esc.stage === 'tester') ? esc : null
      // a decisão fica no topo; os corpos não repetem o painel
      const calm: TaskView = local ? { ...view, escalation: null } : view
      return (
        <>
          {local && <Escalation reason={local.reason} runs={view.test_runs} epicId={null} />}
          <DeveloperBody view={calm} stage={stages.developer} />
          <TesterBody view={calm} stage={stages.tester} />
        </>
      )
    }
    case 'next':
      return <NextBatch view={view} />
    case 'review': {
      const lane = reviewLane(view)
      if (!lane) return <ReviewerBody view={view} stage={stages.reviewer} />
      return <ReviewerBody view={laneView(view, lane)} stage={lane.stages.reviewer} />
    }
    case 'result':
      return <ResultBody view={view} />
  }
}

function Node({
  node,
  open,
  plain,
  onToggle,
  children,
}: {
  node: TimelineNode
  open: boolean
  /** Card sem tinta: na Execução de épicos quem pinta a vez é o épico. */
  plain: boolean
  onToggle: () => void
  children: ReactNode
}) {
  const bodyId = useId()
  const head = (
    <>
      <span className={styles.n}>{node.name}</span>
      <span className={styles.s}>{node.summary}</span>
      <span className={styles.sp} />
      <span className={styles.m}>{node.meta}</span>
    </>
  )
  return (
    <li
      className={cx(styles.node, styles[node.tone], open && styles.open)}
      data-node={node.key}
      data-tone={node.tone}
    >
      <span className={styles.ic} aria-hidden="true">
        {node.icon}
      </span>
      {node.tone === 'todo' ? (
        <div className={styles.nh}>{head}</div>
      ) : (
        <button
          type="button"
          className={styles.nh}
          aria-expanded={open}
          aria-controls={open ? bodyId : undefined}
          onClick={onToggle}
        >
          {head}
          <span className={styles.chev} aria-hidden="true">
            ›
          </span>
        </button>
      )}
      {open && (
        <div
          id={bodyId}
          role="region"
          aria-label={node.name}
          className={cx(
            styles.nb,
            !plain && CARD[node.tone],
            node.key === 'result' && node.tone === 'done' && styles.ok,
          )}
        >
          {children}
        </div>
      )}
    </li>
  )
}

/** Escolha do usuário num nó (abrir/fechar): vale enquanto o nó não muda de estado. */
interface Choice {
  open: boolean
  tone: NodeTone
}

/**
 * A tarefa como linha do tempo de agentes: o que passou vira uma linha, o atual fica aberto, o que vem
 * fica cinza. A ação mora no nó que precisa de você. Monte com `key={task_id}`.
 */
export function TaskTimeline({ view }: { view: TaskView }) {
  const progress = useCrewStore((s) => s.progress)
  const [choices, setChoices] = useState<Partial<Record<NodeKey, Choice>>>({})
  const live: TaskView = { ...view, stages: liveStages(view.stages, progress) }
  const nodes = timelineNodes(live)
  // a escolha solta quando o nó muda de estado (padrão "estado derivado do render", sem efeito)
  const valid: Partial<Record<NodeKey, Choice>> = Object.fromEntries(
    Object.entries(choices).filter(([key, c]) =>
      nodes.some((n) => n.key === key && n.tone === c.tone),
    ),
  )
  if (Object.keys(valid).length !== Object.keys(choices).length) setChoices(valid)

  return (
    <ol className={styles.tl} aria-label="Linha do tempo da tarefa">
      {nodes.map((node) => {
        const choice = valid[node.key]
        const open = node.tone !== 'todo' && (choice ? choice.open : opensByDefault(node, live))
        const failed = node.tone === 'err' ? failedStage(live, node.key) : null
        return (
          <Node
            key={node.key}
            node={node}
            open={open}
            plain={node.key === 'execution' && isSplit(live)}
            onToggle={() => {
              setChoices((current) => ({
                ...current,
                [node.key]: { open: !open, tone: node.tone },
              }))
            }}
          >
            {node.tone === 'pause' && live.limit && <LimitBanner limit={live.limit} />}
            {failed?.now && <h3 className={styles.cause}>{failed.now}</h3>}
            <NodeBody node={node} view={live} />
            {/* os outros corpos já trazem o log do estágio */}
            {failed && node.key === 'interview' && <ActivityLog logs={failed.logs} />}
          </Node>
        )
      })}
    </ol>
  )
}
