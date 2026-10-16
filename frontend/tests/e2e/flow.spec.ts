import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// `speed=8`: o cenário mock roda 8x mais rápido (o fluxo todo leva ~2s).
const FAST = 'speed=8'

/** Nó da linha do tempo, o cabeçalho clicável e o card aberto. */
const node = (page: Page, key: string) => page.locator(`[data-node="${key}"]`)
const header = (page: Page, key: string) => page.locator(`[data-node="${key}"] > button`)
const body = (page: Page, key: string) => page.locator(`[data-node="${key}"] > [role="region"]`)

/** O app sempre abre em "Nova tarefa"; a tarefa da fixture fica atrás do aviso "ver tarefa". */
async function openFixture(page: Page, name: string) {
  await page.goto(`/?fixture=${name}`)
  await page.getByRole('button', { name: 'ver tarefa' }).click()
}

async function startTask(
  page: Page,
  title = 'Filtro por intervalo de datas no relatório de vendas',
) {
  await page.getByLabel('título').fill(title)
  await page.getByRole('button', { name: 'Começar' }).click()
  await expect(page.getByText('T-107')).toBeVisible()
}

/** Começa e aceita as recomendações das 2 rodadas da entrevista do cenário mock. */
async function startTaskToPlan(page: Page) {
  await startTask(page)
  await expect(node(page, 'interview')).toHaveAttribute('data-tone', 'you')
  await page.getByRole('heading', { name: '2 perguntas nesta rodada' }).waitFor()
  await page.getByRole('button', { name: 'Aceitar todas as recomendações' }).click()
  await page.getByRole('heading', { name: '1 pergunta nesta rodada' }).waitFor()
  await page.getByRole('button', { name: 'Aceitar todas as recomendações' }).click()
}

test.describe('modo mock (MSW) — fluxo completo', () => {
  test('da tarefa à conclusão, com 1º teste falhando e 1º review pedindo mudanças', async ({
    page,
  }) => {
    await page.goto(`/?${FAST}`)
    await expect(page.getByRole('heading', { name: 'O que a equipe vai fazer?' })).toBeVisible()

    await startTaskToPlan(page)
    await expect(page.getByRole('button', { name: 'cancelar tarefa' })).toBeVisible()

    // aprovação: o nó do Planner abre sozinho na sua vez
    await expect(node(page, 'plan')).toHaveAttribute('data-tone', 'you')
    await expect(body(page, 'plan').getByText('Critérios de aceite', { exact: true })).toBeVisible()
    await page.getByRole('button', { name: 'Aprovar plano' }).click()

    // loop completo até concluir
    await expect(node(page, 'result')).toHaveAttribute('data-tone', 'done', { timeout: 30_000 })

    // a Execução guarda a 1ª execução que falhou; o Reviewer, o comentário resolvido
    await header(page, 'execution').click()
    await expect(body(page, 'execution')).toContainText('48/48')
    await expect(body(page, 'execution').getByText('FALHOU', { exact: true })).toBeVisible()
    await header(page, 'review').click()
    await expect(body(page, 'review')).toContainText('APROVADO')
    await expect(body(page, 'review').getByText('RESOLVIDO').first()).toBeVisible()

    // resultado + copiar mensagem de commit
    await expect(page.getByText('Mensagem de commit sugerida')).toBeVisible()
    await page.getByRole('button', { name: 'Copiar mensagem' }).click()
    await expect(page.getByRole('button', { name: 'Copiado' })).toBeVisible()
    const clipboard = await page.evaluate(() => navigator.clipboard.readText())
    expect(clipboard).toMatch(/^feat: filtro por intervalo/)

    // Alterações estilo git
    await page.getByRole('button', { name: /^Alterações/ }).click()
    await expect(page.getByRole('heading', { name: 'Alterações' })).toBeVisible()
    await expect(page.getByRole('table', { name: /^Diff de / })).toBeVisible()

    // + Nova → volta à nova tarefa
    await page.getByRole('button', { name: '+ Nova' }).click()
    await expect(page.getByLabel('título')).toBeVisible()
  })

  test('entrevista em 2 rodadas até o plano', async ({ page }) => {
    await page.goto(`/?${FAST}`)
    await startTask(page, 'Exportar pedidos filtrados em CSV')

    await expect(node(page, 'interview')).toHaveAttribute('data-tone', 'you')
    // rodada 1: aceita a 1ª, responde a 2ª com texto próprio
    const criteria = page.getByRole('group', { name: /Critérios de aceite/ })
    await criteria.getByRole('radio', { name: 'Outra resposta' }).check()
    await criteria.getByRole('textbox').fill('Intervalo inclusivo')
    await page.getByRole('button', { name: 'Enviar respostas' }).click()
    // rodada 2: escolhe a alternativa não recomendada
    const restrictions = page.getByRole('group', { name: /Restrições/ })
    await restrictions.getByRole('radio', { name: /Pode adicionar dependências/ }).check()
    await page.getByRole('button', { name: 'Enviar respostas' }).click()

    await expect(node(page, 'plan')).toHaveAttribute('data-tone', 'you', { timeout: 15_000 })
    await expect(node(page, 'interview')).toHaveAttribute('data-tone', 'done')
    await expect(body(page, 'interview')).toHaveCount(0)
  })

  test('escalada (?escalate=1): instruir o Developer retoma e conclui', async ({ page }) => {
    await page.goto(`/?${FAST}&escalate=1`)
    await startTaskToPlan(page)
    await expect(node(page, 'plan')).toHaveAttribute('data-tone', 'you')
    await page.getByRole('button', { name: 'Aprovar plano' }).click()

    await expect(node(page, 'execution')).toHaveAttribute('data-tone', 'you', { timeout: 30_000 })
    await expect(page.getByText('Loop estourou — o que fazer?')).toBeVisible()
    for (const name of ['+2 tentativas', 'Voltar pro Planner', 'Cancelar tarefa']) {
      await expect(page.getByRole('button', { name, exact: true })).toBeVisible()
    }
    await page.getByLabel('Instrução pro Developer').fill('usar fake timers')
    await page.getByRole('button', { name: 'Enviar instrução' }).click()

    await expect(node(page, 'result')).toHaveAttribute('data-tone', 'done', { timeout: 30_000 })
  })

  test('épicos: o escalado abre dentro da Execução, agrupado por quem age', async ({ page }) => {
    await page.goto(`/?${FAST}`)
    await startTask(page, 'Exportar pedidos em CSV com épicos')
    for (let i = 0; i < 2; i += 1) {
      await page.getByRole('button', { name: 'Aceitar todas as recomendações' }).click()
    }
    await page.getByRole('button', { name: /^Aprovar e rodar/ }).click()

    const execution = body(page, 'execution')
    await expect(execution.getByRole('region', { name: 'precisa de você' })).toContainText('E2')
    await expect(execution.getByLabel('Última saída do Tester')).toBeVisible()
    await expect(execution.getByRole('region', { name: 'rodando' })).toContainText('trabalhando')
  })

  test('cancelar tarefa pede confirmação e libera a nova tarefa', async ({ page }) => {
    page.on('dialog', (dialog) => {
      void dialog.accept()
    })
    await page.goto(`/?${FAST}`)
    await startTask(page)
    await page.getByRole('button', { name: 'cancelar tarefa' }).click()
    await expect(page).toHaveTitle(/Cancelada/)
    await page.getByRole('button', { name: '+ Nova' }).click()
    await expect(page.getByLabel('título')).toBeVisible()
  })
})

test.describe('modo mock — histórico', () => {
  test('reabre uma tarefa antiga e mostra o diff de um arquivo', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('tab', { name: 'Histórico' }).click()
    await page.getByRole('button', { name: 'Exportar pedidos em CSV' }).click()

    const past = page.getByRole('region', { name: 'Tarefa T-104' })
    await past.getByTitle('src/export/csv.ts').click()
    await expect(past.getByRole('table', { name: 'Diff de src/export/csv.ts' })).toContainText(
      '+export const total',
    )

    await past.getByRole('button', { name: '← Histórico' }).click()
    await expect(page.getByRole('list', { name: 'Histórico de tarefas' })).toBeVisible()
  })
})

test.describe('modo mock — fixtures estáticas e conexão', () => {
  test('?fixture=escalated renderiza o estado e recusa comandos (somente leitura)', async ({
    page,
  }) => {
    await openFixture(page, 'escalated')
    await expect(node(page, 'execution')).toHaveAttribute('data-tone', 'you')
    await page.getByRole('button', { name: '+2 tentativas' }).click()
    await expect(page.getByRole('alert')).toContainText('Modo fixture: somente leitura.')
  })

  test('?fixture=next-batch, limited e failed desenham o nó que pede você', async ({ page }) => {
    await openFixture(page, 'next-batch')
    await expect(node(page, 'next')).toHaveAttribute('data-tone', 'you')
    await openFixture(page, 'limited')
    await expect(body(page, 'execution').getByRole('button', { name: 'Retomar' })).toBeVisible()
    await page.goto('/?fixture=failed')
    await page.getByRole('tab', { name: 'Tarefa' }).click()
    await expect(node(page, 'execution')).toHaveAttribute('data-tone', 'err')
  })

  test('fixture inexistente mostra o erro na tela (e lista as disponíveis)', async ({ page }) => {
    page.on('pageerror', () => undefined) // o erro também é relançado no console
    await page.goto('/?fixture=nao-existe')
    await expect(page.getByText(/Fixture "nao-existe" não existe/)).toBeVisible()
    await expect(page.getByText(/escalated/)).toBeVisible()
  })

  test('queda do WS mostra "reconectando…" e some quando reconecta', async ({ page }) => {
    await page.goto(`/?${FAST}`)
    await expect(page.getByLabel('título')).toBeVisible()
    await page.getByRole('button', { name: 'derrubar ws' }).click()
    await expect(page.getByRole('status')).toHaveText('reconectando…')
    await expect(page.getByRole('status')).toBeHidden({ timeout: 10_000 })
  })

  test('celular: o card aberto ocupa a largura toda', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await openFixture(page, 'escalated')
    const card = await body(page, 'execution').boundingBox()
    expect(card?.width).toBeGreaterThan(390 - 2 * 16 - 2)
  })

  test('celular: o card aberto não passa da largura da tela', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    for (const name of ['escalated', 'epics', 'next-batch', 'limited', 'failed']) {
      if (name === 'failed') {
        // tarefa terminada: sem aviso "ver tarefa", abre pela aba
        await page.goto('/?fixture=failed')
        await page.getByRole('tab', { name: 'Tarefa' }).click()
      } else {
        await openFixture(page, name)
      }
      await expect(page.locator('[data-node] > [role="region"]').first()).toBeVisible()
      const width = await page.evaluate(() => document.documentElement.scrollWidth)
      expect(width, name).toBeLessThanOrEqual(390)
    }
  })

  test('celular: a pergunta da entrevista fica dentro da borda', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await openFixture(page, 'interviewing')
    const fields = await page.locator('fieldset').all()
    expect(fields.length).toBeGreaterThan(0)
    for (const field of fields) {
      const box = await field.boundingBox()
      const legend = await field.locator('legend').boundingBox()
      // legenda padrão senta em cima da borda (topo igual ao do fieldset)
      expect(legend?.y ?? 0).toBeGreaterThan(box?.y ?? 0)
    }
  })

  test('celular: a barra de aprovação fecha o card, sem vão no fim', async ({ page }) => {
    // um print fullPage congela a barra sticky na altura da janela e mostra o lugar dela vazio;
    // rolando de verdade até o fim do card a barra assenta no lugar
    await page.setViewportSize({ width: 390, height: 844 })
    await openFixture(page, 'awaiting_approval')
    const card = body(page, 'plan')
    await card.evaluate((el) => {
      el.scrollIntoView({ block: 'end' })
    })
    const box = await card.boundingBox()
    const bar = await card
      .getByRole('button', { name: 'Aprovar plano' })
      .locator('..')
      .boundingBox()
    const end = (box?.y ?? 0) + (box?.height ?? 0)
    expect(end - ((bar?.y ?? 0) + (bar?.height ?? 0))).toBeLessThan(30)
  })

  test('celular: Adicionar pasta cabe no diálogo', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 })
    await page.goto('/')
    await page.getByRole('combobox', { name: 'repositório' }).click()
    await page.getByRole('option', { name: /Adicionar pasta/ }).click()
    const dialog = page.getByRole('dialog')
    await expect(dialog.getByRole('button', { name: 'Selecionar' }).first()).toBeVisible()
    const box = await dialog.boundingBox()
    const buttons = await dialog.getByRole('button', { name: 'Selecionar' }).all()
    for (const button of buttons) {
      const b = await button.boundingBox()
      expect((b?.x ?? 0) + (b?.width ?? 0)).toBeLessThanOrEqual((box?.x ?? 0) + (box?.width ?? 0))
    }
  })
})
