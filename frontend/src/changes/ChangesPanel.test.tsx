import { screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { http, HttpResponse } from 'msw'
import { describe, expect, it } from 'vitest'
import { fixture } from '../test/fixtures'
import { renderWithClient } from '../test/render'
import { server } from '../test/server'
import { ChangesPanel } from './ChangesPanel'

const view = fixture('done')
const files = view.final?.files ?? []

describe('ChangesPanel', () => {
  it('árvore por pasta; abre o diff do primeiro arquivo e troca no clique', async () => {
    const asked: string[] = []
    server.use(
      http.get('*/api/tasks/:id/diff', ({ params, request }) => {
        const path = new URL(request.url).searchParams.get('path') ?? ''
        asked.push(`${String(params.id)} ${path}`)
        return HttpResponse.json({
          path,
          status: 'M',
          patch: 'diff --git a/x b/x\r\n--- a/x\n+++ b/x\n@@ -1,2 +1,2 @@\n ctx\n-old\n+new\n',
          binary: false,
          truncated: true,
        })
      }),
    )
    const user = userEvent.setup()
    renderWithClient(<ChangesPanel taskId={view.task_id} files={files} />)

    expect(screen.getByText('▾ shop/')).toBeInTheDocument()
    const first = files[0]?.path ?? ''
    expect(screen.getByTitle(first)).toHaveAttribute('aria-current', 'true')
    // o cabeçalho do git fica de fora; linhas numeradas antes/depois
    const table = await screen.findByRole('table', { name: `Diff de ${first}` })
    expect(table.textContent).toBe('@@ -1,2 +1,2 @@11 ctx2−old2+new')
    expect(screen.getByText(/Diff cortado/)).toBeInTheDocument()

    await user.click(screen.getByTitle('tests/test_report_dates.py'))
    expect(
      await screen.findByRole('table', { name: 'Diff de tests/test_report_dates.py' }),
    ).toBeInTheDocument()
    expect(asked).toEqual([`T-107 ${first}`, 'T-107 tests/test_report_dates.py'])
  })

  it('worktree removido: mostra o motivo no lugar do patch', async () => {
    server.use(
      http.get('*/api/tasks/:id/diff', () =>
        HttpResponse.json({ detail: 'worktree removido: diff indisponível' }, { status: 404 }),
      ),
    )
    renderWithClient(<ChangesPanel taskId={view.task_id} files={files} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('worktree removido')
  })

  it('arquivo binário não mostra patch', async () => {
    server.use(
      http.get('*/api/tasks/:id/diff', () =>
        HttpResponse.json({
          path: 'shop/api.py',
          status: 'M',
          patch: '',
          binary: true,
          truncated: false,
        }),
      ),
    )
    renderWithClient(<ChangesPanel taskId={view.task_id} files={files} />)
    expect(await screen.findByText(/Arquivo binário/)).toBeInTheDocument()
  })
})
