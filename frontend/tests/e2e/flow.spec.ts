import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// `speed=8`: o cenário mock roda 8x mais rápido (o fluxo todo leva ~2s).
const FAST = 'speed=8'

const card = (page: Page, key: string) => page.locator(`[data-stage="${key}"]`)
/** O que se clica: a aba do trilho (tela da tarefa) ou o header do card de origem (nova tarefa). */
const header = (page: Page, key: string) =>
  page.locator(`[data-stage="${key}"][role="tab"], [data-stage="${key}"] > button`).first()
const panel = (page: Page) => page.locator('#focus-panel')

/** O app sempre abre em "Nova tarefa"; a tarefa da fixture fica atrás do aviso "ver tarefa". */
async function openFixture(page: Page, name: string) {
  await page.goto(`/?fixture=${name}`)
  await page.getByRole('button', { name: 'ver tarefa' }).click()
}

async function startTask(page: Page) {
  await header(page, 'manual').click()
  await page.getByLabel('título').fill('Filtro por intervalo de datas no relatório de vendas')
  await page.getByRole('button', { name: 'Iniciar' }).click()
  await expect(page.getByText('T-107')).toBeVisible()
}

/** Inicia e aceita as recomendações das 2 rodadas da entrevista do cenário mock. */
async function startTaskToPlan(page: Page) {
  await startTask(page)
  await expect(card(page, 'interviewer')).toHaveAttribute('data-status', 'waiting')
  await header(page, 'interviewer').click()
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

    // estado inicial: só os cards de origem
    await expect(card(page, 'manual')).toHaveAttribute('data-status', 'pick')
    await expect(page.getByText('escolha a origem da tarefa ↑')).toBeVisible()

    await startTaskToPlan(page)
    await expect(card(page, 'manual')).toHaveAttribute('data-status', 'done')
    await expect(page.getByRole('button', { name: 'cancelar tarefa' })).toBeVisible()

    // aprovação: espera o plano; o foco vai sozinho pra ela
    await expect(card(page, 'approval')).toHaveAttribute('data-status', 'waiting')
    await expect(header(page, 'approval')).toHaveAttribute('aria-selected', 'true')
    await expect(panel(page).getByText('Critérios de aceite', { exact: true })).toBeVisible() // <summary> do plano
    await page.getByRole('button', { name: 'Aprovar plano' }).click()

    // loop completo até concluir
    await expect(card(page, 'done')).toHaveAttribute('data-status', 'done', { timeout: 30_000 })
    await expect(card(page, 'developer')).toContainText('rodada 3')

    // Tester guarda a 1ª execução que falhou; Reviewer, o comentário resolvido
    await header(page, 'tester').click()
    await expect(panel(page)).toContainText('PASSOU · 48/48')
    await expect(panel(page).getByText('FALHOU', { exact: true })).toBeVisible()
    await header(page, 'reviewer').click()
    await expect(panel(page)).toContainText('APROVADO')
    await expect(panel(page).getByText('RESOLVIDO').first()).toBeVisible()

    // relatório final + copiar mensagem de commit
    await header(page, 'done').click()
    await expect(page.getByText('Mensagem de commit sugerida')).toBeVisible()
    await page.getByRole('button', { name: 'Copiar mensagem' }).click()
    await expect(page.getByRole('button', { name: 'Copiado' })).toBeVisible()
    const clipboard = await page.evaluate(() => navigator.clipboard.readText())
    expect(clipboard).toMatch(/^feat: filtro por intervalo/)

    // Nova tarefa → volta ao menu de origem
    await page.getByRole('tab', { name: 'Nova tarefa' }).click()
    await expect(card(page, 'manual')).toHaveAttribute('data-status', 'pick')
  })

  test('Manual: entrevista em 2 rodadas até o plano', async ({ page }) => {
    await page.goto(`/?${FAST}`)
    await header(page, 'manual').click()
    await page.getByLabel('título').fill('Exportar pedidos filtrados em CSV')
    await page.getByRole('button', { name: 'Iniciar' }).click()

    await expect(card(page, 'interviewer')).toHaveAttribute('data-status', 'waiting')
    await header(page, 'interviewer').click()
    // rodada 1: aceita a 1ª, responde a 2ª com texto próprio
    const criteria = page.getByRole('group', { name: /Critérios de aceite/ })
    await criteria.getByRole('radio', { name: 'Outra resposta' }).check()
    await criteria.getByRole('textbox').fill('Intervalo inclusivo')
    await page.getByRole('button', { name: 'Enviar respostas' }).click()
    // rodada 2: escolhe a alternativa não recomendada
    const restrictions = page.getByRole('group', { name: /Restrições/ })
    await restrictions.getByRole('radio', { name: /Pode adicionar dependências/ }).check()
    await page.getByRole('button', { name: 'Enviar respostas' }).click()

    await expect(card(page, 'approval')).toHaveAttribute('data-status', 'waiting', {
      timeout: 15_000,
    })
    await expect(card(page, 'interviewer')).toHaveAttribute('data-status', 'done')
    await expect(header(page, 'interviewer')).toHaveAttribute('aria-selected', 'false')
  })

  test('escalada (?escalate=1): instruir o Developer retoma e conclui', async ({ page }) => {
    await page.goto(`/?${FAST}&escalate=1`)
    await startTaskToPlan(page)
    await expect(card(page, 'approval')).toHaveAttribute('data-status', 'waiting')
    await header(page, 'approval').click()
    await page.getByRole('button', { name: 'Aprovar plano' }).click()

    await expect(panel(page)).toContainText('Limite 3/3 atingido', { timeout: 30_000 })
    await expect(card(page, 'tester')).toHaveAttribute('data-status', 'error')
    await expect(header(page, 'tester')).toHaveAttribute('aria-selected', 'true') // foco no que precisa de você
    await expect(page.getByText('Loop estourou — o que fazer?')).toBeVisible()
    for (const name of ['+2 tentativas', 'Voltar pro Planner', 'Cancelar tarefa']) {
      await expect(page.getByRole('button', { name, exact: true })).toBeVisible()
    }
    await page.getByLabel('Instrução pro Developer').fill('usar fake timers')
    await page.getByRole('button', { name: 'Enviar instrução' }).click()

    await expect(card(page, 'done')).toHaveAttribute('data-status', 'done', { timeout: 30_000 })
  })

  test('cancelar tarefa pede confirmação e libera "Nova tarefa"', async ({ page }) => {
    page.on('dialog', (dialog) => {
      void dialog.accept()
    })
    await page.goto(`/?${FAST}`)
    await startTask(page)
    await page.getByRole('button', { name: 'cancelar tarefa' }).click()
    await expect(page.getByRole('region', { name: 'Agora' })).toContainText('Cancelada')
    await page.getByRole('tab', { name: 'Nova tarefa' }).click()
    await expect(card(page, 'manual')).toHaveAttribute('data-status', 'pick')
  })
})

test.describe('modo mock — histórico', () => {
  test('reabre uma tarefa antiga e mostra o diff de um arquivo', async ({ page }) => {
    await page.goto('/')
    await page.getByRole('tab', { name: 'Histórico' }).click()
    await page.getByRole('button', { name: 'Exportar pedidos em CSV' }).click()

    const past = page.getByRole('region', { name: 'Tarefa T-104' })
    await past.getByTitle('src/export/csv.ts').click()
    await expect(past.getByLabel('Diff de src/export/csv.ts')).toContainText('+export const total')

    await past.getByRole('button', { name: '← Histórico' }).click()
    await expect(page.getByRole('list', { name: 'Histórico de tarefas' })).toBeVisible()
  })
})

test.describe('modo mock — fixtures estáticas e conexão', () => {
  test('?fixture=escalated renderiza o estado e recusa comandos (somente leitura)', async ({
    page,
  }) => {
    await openFixture(page, 'escalated')
    await expect(card(page, 'tester')).toHaveAttribute('data-status', 'error')
    await header(page, 'tester').click()
    await page.getByRole('button', { name: '+2 tentativas' }).click()
    await expect(page.getByRole('alert')).toContainText('Modo fixture: somente leitura.')
  })

  test('fixture inexistente mostra o erro na tela (e lista as disponíveis)', async ({ page }) => {
    page.on('pageerror', () => undefined) // o erro também é relançado no console
    await page.goto('/?fixture=nao-existe')
    await expect(page.getByText(/Fixture "nao-existe" não existe/)).toBeVisible()
    await expect(page.getByText(/escalated/)).toBeVisible()
  })

  test('queda do WS mostra "reconectando…" e some quando reconecta', async ({ page }) => {
    await page.goto(`/?${FAST}`)
    await expect(card(page, 'manual')).toBeVisible()
    await page.getByRole('button', { name: 'derrubar ws' }).click()
    await expect(page.getByRole('status')).toHaveText('reconectando…')
    await expect(page.getByRole('status')).toBeHidden({ timeout: 10_000 })
  })

  test('/dev/gallery mostra todos os status do StageCard', async ({ page }) => {
    await page.goto('/dev/gallery')
    for (const status of ['pick', 'idle', 'active', 'waiting', 'done', 'error', 'skipped']) {
      await expect(page.locator(`[data-status="${status}"]`).first()).toBeVisible()
    }
  })

  test('reduced motion: sem animação nos conectores ativos', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' })
    await openFixture(page, 'developing')
    const active = page.locator('[data-connector][data-state="active"]').first()
    await expect(active).toBeVisible()
    const animation = await active.evaluate((el) => getComputedStyle(el).animationName)
    expect(animation).toBe('none')
  })
})
