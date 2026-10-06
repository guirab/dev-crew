import { useCrewConnection } from '../api/useCrewConnection'

/** Mantém o WS `/ws` ligado ao store enquanto montado. Não renderiza nada. */
export function CrewConnection() {
  useCrewConnection()
  return null
}
