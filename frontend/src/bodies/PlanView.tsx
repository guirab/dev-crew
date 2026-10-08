import type { ReactNode } from 'react'
import type { Estimate, Plan } from '../contracts/generated'
import { EpicList } from './EpicList'
import type { EpicSelection } from './EpicList'
import { EstimateBox } from './EstimateBox'
import b from './body.module.css'

const CHANGE_LABEL = { A: 'adicionado', M: 'modificado', D: 'removido' } as const

/** Fração da estimativa que cabe aos épicos marcados (1 = plano inteiro). */
export function selectedShare(estimate: Estimate, selected: ReadonlySet<string>): number {
  if (estimate.epics.length === 0) return 1
  const total = estimate.epics.reduce((sum, e) => sum + e.usd, 0)
  if (total <= 0) return 1
  const chosen = estimate.epics
    .filter((e) => selected.has(e.epic_id))
    .reduce((s, e) => s + e.usd, 0)
  return chosen / total
}

/** Seção recolhida (fechada por padrão), com `<details>` nativo pra não perder o estado ao atualizar. */
function Fold({ title, children }: { title: string; children: ReactNode }) {
  return (
    <details className={b.fold}>
      <summary>{title}</summary>
      {children}
    </details>
  )
}

/**
 * Plano completo (reusado pelo Planner e pela Aprovação). Resumo, passos (ou épicos) e riscos ficam
 * à vista; o resto abre sob demanda. Plano dividido mostra os épicos no lugar dos passos; com
 * `selection`, cada épico pode ser marcado pra rodar agora.
 */
export function PlanView({
  plan,
  estimate = null,
  selection,
}: {
  plan: Plan
  estimate?: Estimate | null
  selection?: EpicSelection
}) {
  const split = plan.execution === 'epics' && plan.epics.length > 0
  return (
    <>
      <div className={b.sec}>
        <h4>Plano{split ? ' dividido em épicos' : ''}</h4>
        <p style={{ margin: '0 0 10px' }}>{plan.summary}</p>
        {!split && (
          <ol>
            {plan.steps.map((step, i) => (
              <li key={`${i}|${step}`}>{step}</li>
            ))}
          </ol>
        )}
      </div>
      {split && (
        <EpicList epics={plan.epics} estimates={estimate?.epics ?? []} selection={selection} />
      )}
      {plan.risks.length > 0 && (
        <div className={b.sec}>
          <h4>Riscos</h4>
          <ul>
            {plan.risks.map((risk, i) => (
              <li key={`${i}|${risk}`}>{risk}</li>
            ))}
          </ul>
        </div>
      )}
      {plan.project_setup && (
        <div className={b.sec}>
          <h4>Projeto novo</h4>
          <p style={{ margin: '0 0 6px' }}>{plan.project_setup.stack}</p>
          <ul className={b.mono}>
            {plan.project_setup.setup_cmd && <li>setup: {plan.project_setup.setup_cmd}</li>}
            <li>testes: {plan.project_setup.test_cmd}</li>
            {plan.project_setup.lint_cmd && <li>lint: {plan.project_setup.lint_cmd}</li>}
            {plan.project_setup.sandbox_image && (
              <li>container: {plan.project_setup.sandbox_image}</li>
            )}
          </ul>
          <p className={b.muted} style={{ margin: '6px 0 0' }}>
            Esta tarefa roda na sua máquina; o setup instala as dependências antes do primeiro
            Tester de cada épico. O container vale a partir da próxima tarefa.
          </p>
        </div>
      )}
      {plan.essential_code && (
        <div className={b.sec}>
          <h4>Código essencial</h4>
          <pre className={b.code}>
            <code>{plan.essential_code}</code>
          </pre>
        </div>
      )}
      {!split && (
        <Fold title="Arquivos">
          <div className={b.chips}>
            {plan.files.map((file) => (
              <span
                key={file.path}
                className={b.chip}
                data-change={file.change}
                title={CHANGE_LABEL[file.change]}
              >
                {file.path}
              </span>
            ))}
          </div>
        </Fold>
      )}
      <Fold title="Critérios de aceite">
        <ul>
          {plan.acceptance_criteria.map((criterion, i) => (
            <li key={`${i}|${criterion}`}>{criterion}</li>
          ))}
        </ul>
      </Fold>
      {plan.test_strategy && (
        <Fold title="Estratégia de testes">
          <p style={{ margin: 0 }}>{plan.test_strategy}</p>
        </Fold>
      )}
      {plan.split_rationale && (
        <Fold title="Por que assim">
          <p style={{ margin: 0 }}>{plan.split_rationale}</p>
        </Fold>
      )}
      {estimate && (
        <EstimateBox
          estimate={estimate}
          share={selection ? selectedShare(estimate, selection.selected) : 1}
        />
      )}
    </>
  )
}
