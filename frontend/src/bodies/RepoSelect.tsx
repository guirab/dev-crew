import { useState } from 'react'
import { useRepos } from '../api/queries'
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
  return (
    <Field label="repositório" inline>
      {(id) => (
        <select
          id={id}
          value={repo ?? ''}
          disabled={!repos.data || repos.data.length === 0}
          onChange={(e) => {
            setRepo(e.target.value)
          }}
        >
          {repos.isPending && <option value="">carregando…</option>}
          {repos.isError && <option value="">erro ao listar repositórios</option>}
          {repos.data?.map((r) => (
            <option key={r.name} value={r.name}>
              {r.name}
            </option>
          ))}
        </select>
      )}
    </Field>
  )
}
