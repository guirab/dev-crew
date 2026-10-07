import { useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSendCommand } from '../api/commands'
import { folderProbeQuery, foldersKey, folderProbeKey, reposQuery } from '../api/queries'
import type { AddRepo } from '../contracts/generated'
import { NAME_RE } from '../lib/repoName'
import { cx } from '../lib/cx'
import { Button } from '../ui/Button'
import { Field } from '../ui/Field'
import { CommandErrorMessage } from './CommandErrorMessage'
import { FolderBrowser } from './FolderBrowser'
import b from './body.module.css'

const splitList = (text: string): string[] =>
  text
    .split(',')
    .map((part) => part.trim())
    .filter((part) => part !== '')

/**
 * Adiciona um repositório git que já existe no disco: o usuário escolhe a pasta no navegador,
 * confirma nome e branch base e informa os comandos. As regras de verdade ficam no backend.
 */
export function AddRepoForm({ onAdded }: { onAdded: () => void }) {
  const [selected, setSelected] = useState<string | null>(null)
  const [nameEdit, setNameEdit] = useState<string | null>(null)
  const [branchEdit, setBranchEdit] = useState<string | null>(null)
  const [testCmd, setTestCmd] = useState('')
  const [lintCmd, setLintCmd] = useState('')
  const [setupCmd, setSetupCmd] = useState('')
  const [sandboxImage, setSandboxImage] = useState('')
  const [depsDirs, setDepsDirs] = useState('')
  const send = useSendCommand()
  const queryClient = useQueryClient()
  const probe = useQuery({ ...folderProbeQuery(selected ?? ''), enabled: selected !== null })

  const probed = selected !== null ? probe.data : undefined
  const name = (nameEdit ?? probed?.name ?? '').trim()
  const branch = (branchEdit ?? probed?.branch ?? 'main').trim()
  const badName = name !== '' && !NAME_RE.test(name)
  const insideRepo = probed?.git === 'inside_repo'
  const canInitGit = (probed?.git === 'none' || probed?.git === 'empty') && send.isError

  const submit = (initGit: boolean) => {
    if (selected === null) return
    const command: AddRepo = {
      type: 'add_repo',
      name,
      path: selected,
      base_branch: branch,
      test_cmd: testCmd.trim(),
      lint_cmd: lintCmd.trim() || null,
      setup_cmd: setupCmd.trim() || null,
      sandbox_image: sandboxImage.trim() || null,
      deps_dirs: splitList(depsDirs),
      init_git: initGit,
    }
    send.mutate(command, {
      onSuccess: () => {
        void queryClient.invalidateQueries({ queryKey: reposQuery.queryKey })
        void queryClient.invalidateQueries({ queryKey: foldersKey })
        void queryClient.invalidateQueries({ queryKey: folderProbeKey })
        onAdded()
      },
    })
  }

  return (
    <>
      <FolderBrowser
        selected={selected}
        onSelect={(path) => {
          setSelected(path)
          setNameEdit(null)
          setBranchEdit(null)
          send.reset()
        }}
      />
      {selected !== null && (
        <>
          <p className={cx(b.muted, b.mono)}>{selected}</p>
          {probe.isError && (
            <p role="alert" className={b.error}>
              {probe.error.message}
            </p>
          )}
          {insideRepo && (
            <p role="alert" className={b.error}>
              Esta pasta fica dentro de outro repositório git. Escolha a pasta raiz do repositório.
            </p>
          )}
          {probed?.git === 'none' && (
            <p className={b.muted}>Esta pasta ainda não é um repositório git.</p>
          )}
          {probed?.git === 'empty' && (
            <p className={b.muted}>Este repositório git ainda não tem nenhum commit.</p>
          )}
          <div className={b.pair}>
            <Field label="nome do repositório">
              {(id) => (
                <input
                  id={id}
                  value={nameEdit ?? probed?.name ?? ''}
                  aria-invalid={badName}
                  onChange={(e) => {
                    setNameEdit(e.target.value)
                  }}
                />
              )}
            </Field>
            <Field label="branch base">
              {(id) => (
                <input
                  id={id}
                  value={branchEdit ?? probed?.branch ?? 'main'}
                  onChange={(e) => {
                    setBranchEdit(e.target.value)
                  }}
                />
              )}
            </Field>
          </div>
          {badName && (
            <p className={b.muted}>Use letras, números, ponto, hífen ou _ (sem espaços, até 64).</p>
          )}
          <Field label="comando de teste · obrigatório">
            {(id) => (
              <input
                id={id}
                value={testCmd}
                placeholder="uv run pytest -q"
                onChange={(e) => {
                  setTestCmd(e.target.value)
                }}
              />
            )}
          </Field>
          <div className={b.pair}>
            <Field label="comando de lint · opcional">
              {(id) => (
                <input
                  id={id}
                  value={lintCmd}
                  placeholder="uv run ruff check ."
                  onChange={(e) => {
                    setLintCmd(e.target.value)
                  }}
                />
              )}
            </Field>
            <Field label="comando de setup · opcional">
              {(id) => (
                <input
                  id={id}
                  value={setupCmd}
                  placeholder="npm ci"
                  onChange={(e) => {
                    setSetupCmd(e.target.value)
                  }}
                />
              )}
            </Field>
          </div>
          <div className={b.pair}>
            <Field label="imagem do sandbox · opcional">
              {(id) => (
                <input
                  id={id}
                  value={sandboxImage}
                  placeholder="node:22"
                  onChange={(e) => {
                    setSandboxImage(e.target.value)
                  }}
                />
              )}
            </Field>
            <Field label="pastas de dependências · opcional, separadas por vírgula">
              {(id) => (
                <input
                  id={id}
                  value={depsDirs}
                  placeholder="node_modules, .venv"
                  onChange={(e) => {
                    setDepsDirs(e.target.value)
                  }}
                />
              )}
            </Field>
          </div>
          <div className={cx(b.row, b.end)}>
            <Button
              variant="primary"
              disabled={
                send.isPending ||
                probed === undefined ||
                insideRepo ||
                name === '' ||
                badName ||
                testCmd.trim() === ''
              }
              onClick={() => {
                submit(false)
              }}
            >
              {send.isPending ? 'Adicionando…' : 'Adicionar repositório'}
            </Button>
          </div>
          <CommandErrorMessage error={send.error} />
          {canInitGit && (
            <div className={b.sec}>
              <p className={b.muted}>
                O dev-crew pode inicializar o git nesta pasta: cria só um commit inicial vazio na
                branch base, sem adicionar nem alterar nenhum arquivo.
              </p>
              <div className={cx(b.row, b.end)}>
                <Button
                  disabled={send.isPending}
                  onClick={() => {
                    submit(true)
                  }}
                >
                  Inicializar o git
                </Button>
              </div>
            </div>
          )}
        </>
      )}
    </>
  )
}
