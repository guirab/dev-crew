import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { foldersQuery } from '../api/queries'
import { Button } from '../ui/Button'
import { cx } from '../lib/cx'
import styles from './FolderBrowser.module.css'

interface FolderBrowserProps {
  /** Pasta escolhida (destaque na lista). */
  selected: string | null
  onSelect: (path: string) => void
}

/**
 * Navegador de pastas do disco (a UI roda numa janela sem seletor nativo): começa na pasta de
 * projetos do gateway, sobe até as unidades e marca repositórios git e pastas já cadastradas.
 */
export function FolderBrowser({ selected, onSelect }: FolderBrowserProps) {
  const [path, setPath] = useState<string | undefined>(undefined)
  const listing = useQuery(foldersQuery(path))
  const data = listing.data
  const parent = data?.parent ?? null

  return (
    <div className={styles.browser}>
      <div className={styles.bar}>
        <Button
          size="sm"
          disabled={parent === null}
          onClick={() => {
            if (parent !== null) setPath(parent)
          }}
        >
          Subir
        </Button>
        <Button
          size="sm"
          onClick={() => {
            setPath('')
          }}
        >
          Unidades
        </Button>
        <span className={styles.path} title={data?.path}>
          {data ? data.path || 'Unidades' : '…'}
        </span>
      </div>
      {listing.isPending && <p className={styles.note}>carregando pastas…</p>}
      {listing.isError && (
        <p role="alert" className={styles.err}>
          {listing.error.message}
        </p>
      )}
      {data?.entries.length === 0 && <p className={styles.note}>nenhuma subpasta aqui</p>}
      {data && data.entries.length > 0 && (
        <ul className={styles.list} aria-label="Pastas">
          {data.entries.map((entry) => (
            <li
              key={entry.path}
              className={cx(styles.item, selected === entry.path && styles.picked)}
            >
              <button
                type="button"
                className={styles.enter}
                onClick={() => {
                  setPath(entry.path)
                }}
              >
                <span aria-hidden="true">▸</span> {entry.name}
              </button>
              {entry.git_repo && <span className={styles.badge}>git</span>}
              {entry.registered && <span className={styles.badge}>já adicionado</span>}
              <Button
                size="sm"
                disabled={entry.registered}
                aria-label={`Selecionar ${entry.name}`}
                aria-pressed={selected === entry.path}
                onClick={() => {
                  onSelect(entry.path)
                }}
              >
                {selected === entry.path ? 'Selecionada' : 'Selecionar'}
              </Button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
