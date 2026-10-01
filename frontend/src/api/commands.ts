import { useMutation } from '@tanstack/react-query'
import type { Command, CommandReply } from '../contracts/generated'
import { useCrewStore } from '../store/crew'
import { postCommand } from './client'
import type { CommandError } from './client'

/**
 * Mutation de comando. Uma instância por componente: `isPending`/`error` ficam locais
 * (botão desabilita durante o envio; erro aparece inline).
 *
 * A `view` da resposta só é aplicada se nenhum snapshot do WS chegou enquanto o POST voava;
 * senão ela seria mais velha que o estado atual.
 */
export function useSendCommand() {
  return useMutation<CommandReply, CommandError, Command, number>({
    mutationFn: postCommand,
    onMutate: () => useCrewStore.getState().viewVersion,
    onSuccess: (reply, _command, versionAtSend) => {
      const store = useCrewStore.getState()
      if (reply.view && store.viewVersion === versionAtSend) store.applyView(reply.view)
    },
  })
}
