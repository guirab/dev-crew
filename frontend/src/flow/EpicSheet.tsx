import { ActivityLog } from '../bodies/ActivityLog'
import b from '../bodies/body.module.css'
import { CopyButton } from '../bodies/CopyButton'
import { Empty } from '../bodies/Empty'
import { EscalationPanel } from '../bodies/EscalationPanel'
import {
  Sheet,
  SheetClose,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from '../components/ui/sheet'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '../components/ui/tabs'
import type { EpicView, TaskView } from '../contracts/generated'
import { formatTokens, formatUsd } from '../lib/format'
import { Button } from '../ui/Button'
import { activityEvents } from './activity'
import { EpicBadge, EpicId, MiniPipeline } from './EpicParts'
import { EPIC_TONE, laneView, mergeDescription } from './lanes'
import { StageBody } from './StageBody'
import styles from './EpicSheet.module.css'

type LaneStage = 'developer' | 'tester' | 'reviewer'
type SheetTab = 'resolve' | LaneStage | 'log'

const STAGES: readonly LaneStage[] = ['developer', 'tester', 'reviewer']

function stageLabel(lane: EpicView, key: LaneStage): string {
  if (key === 'developer') return 'Developer'
  if (key === 'tester') return 'Tester'
  return lane.kind === 'review' ? 'Reviewer' : 'Merge'
}

/** Aba que abre: Resolver na escalada, senão a etapa ativa (ou em erro), senão o Developer. */
function initialTab(lane: EpicView): SheetTab {
  if (lane.escalation) return 'resolve'
  const busy = [...STAGES]
    .reverse()
    .find((key) => ['active', 'error'].includes(lane.stages[key].status))
  return busy ?? 'developer'
}

/** "$0.42 · 7,9 mil tok · depende de E1". */
function laneMeta(lane: EpicView): string {
  return [
    lane.cost_usd > 0 ? formatUsd(lane.cost_usd) : null,
    lane.tokens > 0 ? `${formatTokens(lane.tokens)} tok` : null,
    lane.depends_on.length > 0 ? `depende de ${lane.depends_on.join(', ')}` : null,
  ]
    .filter((part) => part !== null)
    .join(' · ')
}

/** Detalhe de um épico num painel lateral largo. Fecha por Esc, pelo X ou clicando fora. */
export function EpicSheet({
  view,
  lane,
  onClose,
}: {
  view: TaskView
  lane: EpicView | null
  onClose: () => void
}) {
  return (
    <Sheet
      open={lane !== null}
      onOpenChange={(open) => {
        if (!open) onClose()
      }}
    >
      {lane && (
        <SheetContent showCloseButton={false} className={styles.sheet}>
          {/* key: trocar de épico volta pra aba inicial e descarta rascunhos */}
          <EpicDetail key={lane.id} view={view} lane={lane} />
        </SheetContent>
      )}
    </Sheet>
  )
}

function EpicDetail({ view, lane }: { view: TaskView; lane: EpicView }) {
  const meta = laneMeta(lane)
  const path = lane.worktree_path ?? lane.branch
  // a escalada tem aba própria: os corpos das etapas não repetem o painel de decisão
  const pseudo: TaskView = { ...laneView(view, lane), escalation: null }
  const logs = activityEvents(view)
    .filter((event) => event.lane === lane.id)
    .map((event) => ({ ts: event.ts, text: `${event.who} · ${event.text}` }))

  return (
    <>
      <SheetHeader className={styles.hd}>
        <div className={styles.top}>
          <EpicId lane={lane} />
          <SheetTitle className={styles.title}>{lane.title}</SheetTitle>
          <SheetClose asChild>
            <Button size="sm" aria-label="Fechar" className={styles.close}>
              ✕
            </Button>
          </SheetClose>
        </div>
        <div className={styles.meta}>
          <EpicBadge lane={lane} />
          {EPIC_TONE[lane.status] !== 'queued' && <MiniPipeline lane={lane} />}
          {meta && <span className={styles.dim}>{meta}</span>}
        </div>
        <SheetDescription className={styles.goal}>{lane.goal || lane.title}</SheetDescription>
        {path && (
          <div className={styles.path}>
            <code>
              {lane.branch}
              {lane.branch && lane.worktree_path ? ' · ' : ''}
              {lane.worktree_path}
            </code>
            <CopyButton text={path} label="copiar" variant="default" />
          </div>
        )}
      </SheetHeader>

      <Tabs defaultValue={initialTab(lane)} className={styles.tabs}>
        <TabsList variant="line" className={styles.tabList} aria-label="Detalhes do épico">
          {lane.escalation && (
            <TabsTrigger value="resolve">
              <i className={styles.dot} data-status="error" aria-hidden="true" />
              Resolver
            </TabsTrigger>
          )}
          {STAGES.map((key) => (
            <TabsTrigger key={key} value={key}>
              <i className={styles.dot} data-status={lane.stages[key].status} aria-hidden="true" />
              {stageLabel(lane, key)}
            </TabsTrigger>
          ))}
          <TabsTrigger value="log">Log</TabsTrigger>
        </TabsList>

        {lane.escalation && (
          <TabsContent value="resolve" className={styles.body}>
            <Resolve lane={lane} reason={lane.escalation.reason} />
          </TabsContent>
        )}
        {STAGES.map((key) => (
          <TabsContent key={key} value={key} className={styles.body}>
            {key === 'reviewer' && lane.kind !== 'review' && (
              <p className={styles.lead}>{mergeDescription(lane.stages.reviewer)}</p>
            )}
            <StageBody stageKey={key} view={pseudo} stage={lane.stages[key]} />
          </TabsContent>
        ))}
        <TabsContent value="log" className={styles.body}>
          {logs.length > 0 ? <ActivityLog logs={logs} /> : <Empty>Nada ainda.</Empty>}
        </TabsContent>
      </Tabs>
    </>
  )
}

/** A aba da escalada: rodadas, a última saída do Tester e a decisão (ações no rodapé fixo). */
function Resolve({ lane, reason }: { lane: EpicView; reason: string }) {
  const runs = lane.test_runs
  const last = runs.at(-1)
  return (
    <>
      {runs.length > 0 && (
        <div className={b.sec}>
          <h4>Rodadas</h4>
          <ol className={styles.runs}>
            {runs.map((run, i) => (
              <li key={i}>
                <span className={styles.dim}>{i + 1}</span>
                <span>
                  Tester{' '}
                  {run.ok ? (
                    <b className={styles.ok}>passou</b>
                  ) : (
                    <b className={styles.err}>
                      {run.failures.length} falha{run.failures.length === 1 ? '' : 's'}
                    </b>
                  )}
                </span>
                <span className={styles.dim}>
                  {run.passed}/{run.total}
                </span>
              </li>
            ))}
          </ol>
        </div>
      )}
      {last && (
        <div className={b.sec}>
          <h4>Última saída do Tester</h4>
          <pre className={styles.out}>
            <span className={styles.cmd}>$ {last.command}</span>
            {last.failures.map((failure) => (
              <span key={failure.test}>
                {'\n'}
                <span className={styles.err}>FAIL</span> {failure.test}
                {'\n  '}
                {failure.message}
              </span>
            ))}
            {`\n\n${String(last.passed)}/${String(last.total)} passaram`}
          </pre>
        </div>
      )}
      <EscalationPanel reason={reason} epicId={lane.id} actionsClassName={styles.footer} />
    </>
  )
}
