import { expect, test } from '@playwright/test'
import type { Page } from '@playwright/test'

// `speed=8`: o cenário mock roda 8x mais rápido (o fluxo todo leva ~2s).
const FAST = 'speed=8'

const card = (page: Page, key: string) => page.locator(`[data-stage="${key}"]`)
const header = (page: Page, key: string) => card(page, key).getByRole('button').first()

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

    // estado inicial: só o card de origem em pick, tudo fechado
    await expect(card(page, 'manual')).toHaveAttribute('data-status', 'pick')
    await expect(card(page, 'tester')).toHaveAttribute('data-status', 'idle')
    await expect(page.getByText('escolha a origem da tarefa ↑')).toBeVisible()

    await startTaskToPlan(page)
    await expect(card(page, 'manual')).toHaveAttribute('data-status', 'done')
    await expect(page.getByRole('button', { name: 'cancelar tarefa' })).toBeVisible()

    // aprovação: espera o plano, abre (por clique), aprova
    await expect(card(page, 'approval')).toHaveAttribute('data-status', 'waiting')
    await expect(header(page, 'approval')).toHaveAttribute('aria-expanded', 'false')
    await header(page, 'approval').click()
    await expect(page.getByRole('heading', { name: 'Critérios de aceite' })).toBeVisible()
    await page.getByRole('button', { name: 'Aprovar plano' }).click()

    // loop completo até concluir
    await expect(card(page, 'done')).toHaveAttribute('data-status', 'done', { timeout: 30_000 })
    await expect(card(page, 'tester')).toContainText('PASSOU · 48/48')
    await expect(card(page, 'reviewer')).toContainText('APROVADO')
    await expect(card(page, 'developer')).toContainText('rodada 3')
    await expect(page.getByRole('button', { name: 'Nova tarefa' })).toBeVisible()

    // Tester guarda a 1ª execução que falhou; Reviewer, o comentário resolvido
    await header(page, 'tester').click()
    await expect(card(page, 'tester').getByText('FALHOU', { exact: true })).toBeVisible()
    await header(page, 'reviewer').click()
    await expect(card(page, 'reviewer').getByText('RESOLVIDO').first()).toBeVisible()

    // relatório final + copiar mensagem de commit
    await header(page, 'done').click()
    await expect(page.getByText('Mensagem de commit sugerida')).toBeVisible()
    await page.getByRole('button', { name: 'Copiar mensagem' }).click()
    await expect(page.getByRole('button', { name: 'Copiado' })).toBeVisible()
    const clipboard = await page.evaluate(() => navigator.clipboard.readText())
    expect(clipboard).toMatch(/^feat: filtro por intervalo/)

    // Nova tarefa → volta ao estado inicial
    await page.getByRole('button', { name: 'Nova tarefa' }).click()
    await expect(card(page, 'manual')).toHaveAttribute('data-status', 'pick')
    await expect(card(page, 'done')).toHaveAttribute('data-status', 'idle')
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
    await expect(header(page, 'interviewer')).toHaveAttribute('aria-expanded', 'false')
  })

  test('escalada (?escalate=1): instruir o Developer retoma e conclui', async ({ page }) => {
    await page.goto(`/?${FAST}&escalate=1`)
    await startTaskToPlan(page)
    await expect(card(page, 'approval')).toHaveAttribute('data-status', 'waiting')
    await header(page, 'approval').click()
    await page.getByRole('button', { name: 'Aprovar plano' }).click()

    await expect(card(page, 'tester')).toContainText('Limite 3/3 atingido', { timeout: 30_000 })
    await expect(card(page, 'tester')).toHaveAttribute('data-status', 'error')
    await expect(header(page, 'tester')).toHaveAttribute('aria-expanded', 'false') // não auto-expande

    await header(page, 'tester').click()
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
    await expect(page.getByText('cancelada')).toBeVisible()
    await page.getByRole('button', { name: 'Nova tarefa' }).click()
    await expect(card(page, 'manual')).toHaveAttribute('data-status', 'pick')
  })
})

test.describe('modo mock — fixtures estáticas e conexão', () => {
  test('?fixture=escalated renderiza o estado e recusa comandos (somente leitura)', async ({
    page,
  }) => {
    await page.goto('/?fixture=escalated')
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
    await page.goto('/?fixture=developing')
    const active = page.locator('[data-connector][data-state="active"]').first()
    await expect(active).toBeVisible()
    const animation = await active.evaluate((el) => getComputedStyle(el).animationName)
    expect(animation).toBe('none')
  })
})
