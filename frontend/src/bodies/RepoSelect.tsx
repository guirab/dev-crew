import { useState } from 'react'
import { useRepos } from '../api/queries'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '../components/ui/select'
import { Field } from '../ui/Field'

/** Repo escolhido pelo usuário; sem escolha, o primeiro da lista do gateway. */
export function useRepoChoice() {
  const repos = useRepos()
  const [choice, setChoice] = useState<string | null>(null)
  const names = repos.data?.map((r) => r.name) ?? []
  const repo = choice !== null && names.includes(choice) ? choice : (names[0] ?? null)
  return { repo, setRepo: setChoice, repos }
}

export type RepoChoice = ReturnType<typeof useRepoChoice>

export function RepoSelect({ choice }: { choice: RepoChoice }) {
  const { repo, setRepo, repos } = choice
  const hasRepos = !!repos.data && repos.data.length > 0
  const placeholder = repos.isPending
    ? 'carregando…'
    : repos.isError
      ? 'erro ao listar repositórios'
      : 'nenhum repositório'
  return (
    <Field label="repositório" inline>
      {(id) => (
        <Select value={repo ?? undefined} onValueChange={setRepo} disabled={!hasRepos}>
          <SelectTrigger
            id={id}
            className="min-w-48 border-(--line-2) bg-(--glass-bg) text-(--text) backdrop-blur-(--glass-blur)"
          >
            <SelectValue placeholder={placeholder} />
          </SelectTrigger>
          <SelectContent className="border border-(--line-2) bg-(--glass-bg) text-(--text) backdrop-blur-(--glass-blur)">
            {repos.data?.map((r) => (
              <SelectItem key={r.name} value={r.name}>
                {r.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </Field>
  )
}
