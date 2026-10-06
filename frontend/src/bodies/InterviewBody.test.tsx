import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it } from 'vitest'
import { captureCommands } from '../test/commands'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { InterviewBody } from './InterviewBody'

const view = fixture('interviewing')
const CRITERIA = 'Cabeçalho, encoding UTF-8 com BOM e filtro aplicado.'
const LOOSE = 'Só o filtro aplicado; formato livre.'

function setup(overrides = view) {
  return renderWithClient(<InterviewBody view={overrides} stage={overrides.stages.interviewer} />)
}

const group = (topic: RegExp) => screen.getByRole('group', { name: topic })

describe('InterviewBody', () => {
  it('mostra o histórico, a rodada inteira com a recomendação pré-selecionada e a spec', () => {
    setup()
    expect(screen.getByText('✓ Aceito a recomendação.')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: '2 perguntas nesta rodada' })).toBeInTheDocument()
    const criteria = group(/Critérios de aceite/)
    expect(within(criteria).getByRole('radio', { name: new RegExp(CRITERIA) })).toBeChecked()
    expect(within(criteria).getByRole('radio', { name: LOOSE })).not.toBeChecked()
    expect(within(criteria).getByText('recomendada')).toBeInTheDocument()
    expect(within(criteria).getByText(/Excel no Windows/)).toBeInTheDocument() // rationale
    expect(group(/Restrições/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Spec' })).toBeInTheDocument()
  })

  it('"Aceitar todas as recomendações" envia uma resposta null por pergunta', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    setup()
    await user.click(screen.getByRole('button', { name: 'Aceitar todas as recomendações' }))
    await waitFor(() => {
      expect(commands.received).toEqual([{ type: 'answer_interview', answers: [null, null] }])
    })
  })

  it('envia a opção escolhida e a resposta livre; a recomendação vai como null', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    setup()
    await user.click(within(group(/Critérios de aceite/)).getByRole('radio', { name: LOOSE }))
    const restrictions = group(/Restrições/)
    await user.click(within(restrictions).getByRole('radio', { name: 'Outra resposta' }))
    await user.type(
      within(restrictions).getByRole('textbox', { name: 'Outra resposta: Restrições' }),
      'Pode usar pandas',
    )
    await user.click(screen.getByRole('button', { name: 'Enviar respostas' }))
    await waitFor(() => {
      expect(commands.received).toEqual([
        { type: 'answer_interview', answers: [LOOSE, 'Pode usar pandas'] },
      ])
    })
  })

  it('"Outra resposta" sem texto bloqueia o envio; recomendação escolhida de volta vira null', async () => {
    const commands = captureCommands()
    const user = userEvent.setup()
    setup()
    const criteria = group(/Critérios de aceite/)
    await user.click(within(criteria).getByRole('radio', { name: 'Outra resposta' }))
    expect(screen.getByRole('button', { name: 'Enviar respostas' })).toBeDisabled()
    await user.click(within(criteria).getByRole('radio', { name: new RegExp(CRITERIA) }))
    await user.click(screen.getByRole('button', { name: 'Enviar respostas' }))
    await waitFor(() => {
      expect(commands.received).toEqual([{ type: 'answer_interview', answers: [null, null] }])
    })
  })

  it('desabilita os botões durante o envio', async () => {
    const commands = captureCommands()
    commands.hold()
    const user = userEvent.setup()
    setup()
    await user.click(screen.getByRole('button', { name: 'Enviar respostas' }))
    expect(screen.getByRole('button', { name: 'Enviar respostas' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Aceitar todas as recomendações' })).toBeDisabled()
    commands.release()
    await waitFor(() => {
      expect(screen.getByRole('button', { name: 'Enviar respostas' })).toBeEnabled()
    })
  })

  it('mostra o erro do servidor inline e preserva as escolhas', async () => {
    captureCommands({
      status: 409,
      body: { ok: false, error: 'Nenhuma pergunta aguardando resposta.', view: null },
    })
    const user = userEvent.setup()
    setup()
    const loose = within(group(/Critérios de aceite/)).getByRole('radio', { name: LOOSE })
    await user.click(loose)
    await user.click(screen.getByRole('button', { name: 'Enviar respostas' }))
    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Nenhuma pergunta aguardando resposta.',
    )
    expect(loose).toBeChecked()
  })

  it('as escolhas sobrevivem a um novo snapshot da mesma rodada', async () => {
    const user = userEvent.setup()
    const { rerender } = setup()
    await user.click(within(group(/Critérios de aceite/)).getByRole('radio', { name: LOOSE }))
    rerender(<InterviewBody view={{ ...view, cost_usd: 1 }} stage={view.stages.interviewer} />)
    expect(within(group(/Critérios de aceite/)).getByRole('radio', { name: LOOSE })).toBeChecked()
  })

  it('sem rodada aguardando resposta mostra as perguntas sem formulário', () => {
    setup({
      ...view,
      stages: { ...view.stages, interviewer: { ...view.stages.interviewer, status: 'active' } },
    })
    expect(screen.queryByRole('radio')).not.toBeInTheDocument()
    expect(screen.getByText('Quais critérios o Tester deve validar?')).toBeInTheDocument()
  })

  it('sem tarefa: explica quando o estágio entra', () => {
    renderWithClient(<InterviewBody view={null} stage={{ status: 'idle', now: null, logs: [] }} />)
    expect(screen.getByText(/Pergunta em rodadas/)).toBeInTheDocument()
  })
})
