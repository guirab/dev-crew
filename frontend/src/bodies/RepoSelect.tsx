import { useState } from 'react'
import { useRepos } from '../api/queries'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectSeparator,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select'

/** Repo escolhido pelo usuário; sem escolha, o primeiro da lista do gateway. */
export function useRepoChoice() {
  const repos = useRepos()
  const [choice, setChoice] = useState<string | null>(null)
  const names = repos.data?.map((r) => r.name) ?? []
  const repo = choice !== null && names.includes(choice) ? choice : (names[0] ?? null)
  return { repo, setRepo: setChoice, repos }
}

export type RepoChoice = ReturnType<typeof useRepoChoice>

/** Itens de ação no fim do menu: não são repositórios, abrem um formulário. O ":" não cabe num nome de repo. */
export type RepoAction = 'new-project' | 'add-folder'

const ACTION_VALUE: Record<RepoAction, string> = {
  'new-project': ':new-project',
  'add-folder': ':add-folder',
}

const GLASS =
  'min-w-64 border border-(--line-2) bg-[#121618] text-(--text) shadow-[0_24px_50px_rgb(0_0_0/55%)]'

/** Menu do repositório: os registrados, depois Novo projeto e Adicionar pasta existente. */
export function RepoSelect({
  choice,
  onAction,
}: {
  choice: RepoChoice
  onAction: (action: RepoAction) => void
}) {
  const { repo, setRepo, repos } = choice
  const placeholder = repos.isPending
    ? 'carregando…'
    : repos.isError
      ? 'erro ao listar repositórios'
      : 'nenhum repositório'
  return (
    <Select
      value={repo ?? ''}
      onValueChange={(value) => {
        if (value === ACTION_VALUE['new-project']) onAction('new-project')
        else if (value === ACTION_VALUE['add-folder']) onAction('add-folder')
        else setRepo(value)
      }}
    >
      <SelectTrigger
        aria-label="repositório"
        className="h-auto! rounded-full border-(--line-2) bg-(--well) px-3 py-1.5 font-mono text-[12.5px] text-(--text)"
      >
        <span aria-hidden="true">▣</span>
        <SelectValue placeholder={placeholder} />
      </SelectTrigger>
      <SelectContent position="popper" align="start" className={GLASS}>
        {repos.data?.map((r) => (
          <SelectItem key={r.name} value={r.name}>
            {r.name}
          </SelectItem>
        ))}
        {repos.data && repos.data.length > 0 && <SelectSeparator />}
        <SelectItem value={ACTION_VALUE['new-project']}>+ Novo projeto</SelectItem>
        <SelectItem value={ACTION_VALUE['add-folder']}>⌂ Adicionar pasta existente</SelectItem>
      </SelectContent>
    </Select>
  )
}
