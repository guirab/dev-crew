import { useId, useState } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useSendCommand } from '../api/commands'
import { folderProbeQuery, foldersKey, folderProbeKey, reposQuery } from '../api/queries'
import type { AddRepo } from '../contracts/generated'
import { NAME_RE } from '../lib/repoName'
import { cx } from '../lib/cx'
import { Button } from '../ui/Button'
import { Input } from '../ui/Input'
import { Label } from '../ui/Label'
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
  const uid = useId()
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
            <div className={b.field}>
              <Label htmlFor={`${uid}-name`}>nome do repositório</Label>
              <Input
                id={`${uid}-name`}
                value={nameEdit ?? probed?.name ?? ''}
                aria-invalid={badName}
                onChange={(e) => {
                  setNameEdit(e.target.value)
                }}
              />
            </div>
            <div className={b.field}>
              <Label htmlFor={`${uid}-branch`}>branch base</Label>
              <Input
                id={`${uid}-branch`}
                value={branchEdit ?? probed?.branch ?? 'main'}
                onChange={(e) => {
                  setBranchEdit(e.target.value)
                }}
              />
            </div>
          </div>
          {badName && (
            <p className={b.muted}>Use letras, números, ponto, hífen ou _ (sem espaços, até 64).</p>
          )}
          <div className={b.field}>
            <Label htmlFor={`${uid}-test`}>comando de teste · obrigatório</Label>
            <Input
              id={`${uid}-test`}
              value={testCmd}
              placeholder="uv run pytest -q"
              onChange={(e) => {
                setTestCmd(e.target.value)
              }}
            />
          </div>
          <div className={b.pair}>
            <div className={b.field}>
              <Label htmlFor={`${uid}-lint`}>comando de lint · opcional</Label>
              <Input
                id={`${uid}-lint`}
                value={lintCmd}
                placeholder="uv run ruff check ."
                onChange={(e) => {
                  setLintCmd(e.target.value)
                }}
              />
            </div>
            <div className={b.field}>
              <Label htmlFor={`${uid}-setup`}>comando de setup · opcional</Label>
              <Input
                id={`${uid}-setup`}
                value={setupCmd}
                placeholder="npm ci"
                onChange={(e) => {
                  setSetupCmd(e.target.value)
                }}
              />
            </div>
          </div>
          <div className={b.pair}>
            <div className={b.field}>
              <Label htmlFor={`${uid}-image`}>imagem do sandbox · opcional</Label>
              <Input
                id={`${uid}-image`}
                value={sandboxImage}
                placeholder="node:22"
                onChange={(e) => {
                  setSandboxImage(e.target.value)
                }}
              />
            </div>
            <div className={b.field}>
              <Label htmlFor={`${uid}-deps`}>
                pastas de dependências · opcional, separadas por vírgula
              </Label>
              <Input
                id={`${uid}-deps`}
                value={depsDirs}
                placeholder="node_modules, .venv"
                onChange={(e) => {
                  setDepsDirs(e.target.value)
                }}
              />
            </div>
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
