import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { captureCommands } from '../test/commands'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { TesterBody } from './TesterBody'

const escalated = fixture('escalated')

const setup = (view = escalated) =>
  renderWithClient(<TesterBody view={view} stage={view.stages.tester} />)

describe('TesterBody', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('lista as execuções da mais recente pra mais antiga, com falhas e placar', () => {
    setup()
    const heading = screen.getByRole('heading', { name: 'Execuções' })
    const items = Array.from(heading.parentElement?.querySelectorAll('b') ?? []).map(
      (b) => b.textContent,
    )
    expect(items).toEqual(['Tentativa 3', 'Tentativa 2', 'Tentativa 1'])
    expect(screen.getAllByText('FALHOU')).toHaveLength(3)
    expect(screen.getAllByText('46/48')).toHaveLength(3)
    expect(
      screen.getAllByText(
        'tests/test_report_dates.py::test_range_inclusive_end — esperado 12, obtido 9',
      ),
    ).toHaveLength(3)
  })

  it('execução que passou mostra PASSOU e cobertura', () => {
    const done = fixture('done')
    renderWithClient(<TesterBody view={done} stage={done.stages.tester} />)
    expect(screen.getAllByText('PASSOU').length).toBeGreaterThan(0)
    expect(screen.getAllByText('cobertura 87%')).toHaveLength(2)
  })

  describe('escalada', () => {
    it('mostra as 4 opções e o motivo; sem escalada não mostra', () => {
      setup()
      expect(screen.getByText('3 falhas consecutivas de teste')).toBeInTheDocument()
      for (const name of [
        'Enviar instrução',
        '+2 tentativas',
        'Voltar pro Planner',
        'Cancelar tarefa',
      ]) {
        expect(screen.getByRole('button', { name })).toBeInTheDocument()
      }
    })

    it('sem escalada o painel não aparece', () => {
      const running = fixture('testing_failed')
      renderWithClient(<TesterBody view={running} stage={running.stages.tester} />)
      expect(screen.queryByText('Loop estourou — o que fazer?')).not.toBeInTheDocument()
    })

    it('instruir: exige texto e envia escalation/instruct', async () => {
      const commands = captureCommands()
      const user = userEvent.setup()
      setup()
      const send = screen.getByRole('button', { name: 'Enviar instrução' })
      expect(send).toBeDisabled()
      await user.type(screen.getByLabelText('Instrução pro Developer'), 'usar fake timers')
      await user.click(send)
      await waitFor(() => {
        expect(commands.received).toEqual([
          { type: 'escalation', action: 'instruct', text: 'usar fake timers' },
        ])
      })
    })

    it('+2 tentativas e voltar pro Planner enviam a ação correspondente', async () => {
      const commands = captureCommands()
      const user = userEvent.setup()
      setup()
      await user.click(screen.getByRole('button', { name: '+2 tentativas' }))
      await user.click(screen.getByRole('button', { name: 'Voltar pro Planner' }))
      await waitFor(() => {
        expect(commands.received).toEqual([
          { type: 'escalation', action: 'more_attempts' },
          { type: 'escalation', action: 'replan' },
        ])
      })
    })

    it('cancelar pede confirmação; só envia se confirmado', async () => {
      const commands = captureCommands()
      const user = userEvent.setup()
      const confirm = vi.spyOn(window, 'confirm').mockReturnValue(false)
      setup()
      await user.click(screen.getByRole('button', { name: 'Cancelar tarefa' }))
      expect(confirm).toHaveBeenCalledTimes(1)
      expect(commands.received).toEqual([])

      confirm.mockReturnValue(true)
      await user.click(screen.getByRole('button', { name: 'Cancelar tarefa' }))
      await waitFor(() => {
        expect(commands.received).toEqual([{ type: 'cancel_task' }])
      })
    })

    it('desabilita as ações durante o envio e mostra erro inline se recusar', async () => {
      const commands = captureCommands({
        status: 409,
        body: { ok: false, error: 'Não há escalada pendente.', view: null },
      })
      commands.hold()
      const user = userEvent.setup()
      setup()
      await user.click(screen.getByRole('button', { name: '+2 tentativas' }))
      const panel = screen.getByRole('button', { name: 'Voltar pro Planner' })
      expect(panel).toBeDisabled()
      expect(screen.getByRole('button', { name: '+2 tentativas' })).toBeDisabled()

      commands.release()
      const alert = await screen.findByRole('alert')
      expect(within(alert).getByText('Não há escalada pendente.')).toBeInTheDocument()
      expect(screen.getByRole('button', { name: 'Voltar pro Planner' })).toBeEnabled()
    })
  })
})
