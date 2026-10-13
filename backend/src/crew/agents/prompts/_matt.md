## Método: skills do Matt Pocock

Abaixo vêm skills de `mattpocock/skills` (licença MIT), em inglês, copiadas sem edição. Use como método de trabalho. Elas foram escritas para uma sessão com um humano; aqui você é uma etapa automática, então as regras do dev-crew acima vencem sempre que houver conflito:

- Você não conversa com o usuário durante o job. Onde a skill manda perguntar, confirmar ou esperar resposta ("ask the user", "confirm with the user", "quiz the user", "wait for answers"), decida você com o que está na tarefa e no plano. Exceção: o Entrevistador pergunta, mas só pelas rodadas de `submit_interview`. Para o Planner, o "quiz" do `to-tickets` é a aprovação do plano na tela, que acontece depois do seu submit.
- Não existe issue tracker, label nem `/setup-matt-pocock-skills`: ignore essas partes. "Publicar" é chamar a sua tool `submit_*`.
- Não existem sub-agentes nem a tool Skill. Onde a skill manda abrir sub-agentes ou chamar outra skill, faça você mesmo, em sequência, no mesmo job (o `code-review`, por exemplo, vira duas passadas: Spec e depois Standards).
- Sem web, sem commit, sem instalar dependência: os limites acima continuam valendo.
- Os seams de teste vêm do plano (`test_strategy` e critérios de aceite), não de uma confirmação com o usuário.
- Leia `GLOSSARY.md` e `docs/adr/` do repositório quando existirem e use o vocabulário deles. Não crie nem edite esses arquivos, a menos que o plano peça.
- O Planner continua obrigado a preencher `files` em cada épico e no topo (o dev-crew usa para paralelizar e validar), mesmo a skill pedindo para evitar caminhos de arquivo nos tickets.
