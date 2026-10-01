import type { Plan } from '../contracts/generated'
import b from './body.module.css'

const CHANGE_LABEL = { A: 'adicionado', M: 'modificado', D: 'removido' } as const

/** Resumo, passos, arquivos e critérios do plano (reusado pelo Planner e pela Aprovação). */
export function PlanView({ plan }: { plan: Plan }) {
  return (
    <>
      <div className={b.sec}>
        <h4>Plano</h4>
        <p style={{ margin: '0 0 10px' }}>{plan.summary}</p>
        <ol>
          {plan.steps.map((step, i) => (
            <li key={`${i}|${step}`}>{step}</li>
          ))}
        </ol>
      </div>
      <div className={b.sec}>
        <h4>Arquivos</h4>
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
      </div>
      <div className={b.sec}>
        <h4>Critérios de aceite</h4>
        <ul>
          {plan.acceptance_criteria.map((criterion, i) => (
            <li key={`${i}|${criterion}`}>{criterion}</li>
          ))}
        </ul>
      </div>
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
      {plan.test_strategy && (
        <div className={b.sec}>
          <h4>Estratégia de testes</h4>
          <p style={{ margin: 0 }}>{plan.test_strategy}</p>
        </div>
      )}
    </>
  )
}
