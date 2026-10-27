# Como trabalhar com commits

Fluxo de git adotado pela equipe no repositório eVOLVER-CNPEM.

## Branches

| Branch | Uso |
| --- | --- |
| `main` | Versão estável. Não recebe commits diretos. |
| `develop` | Integração das etapas concluídas. Não recebe commits diretos. |
| `etapa-N` / feature | Branch de trabalho da etapa ou funcionalidade em andamento (ex.: `etapa-1`). **Os commits são feitos aqui.** |

## Fluxo de cada commit

Sempre na branch em que se está trabalhando (exemplo com `etapa-1`):

```bash
git checkout etapa-1
git add <arquivos>
git commit -m "Mensagem do commit"
git pull --rebase origin etapa-1   # atualiza a árvore e coloca seus commits no topo
git push origin HEAD:etapa-1       # sobe a branch atual para a branch remota
```

- `git pull --rebase` traz o que os colegas já enviaram e reaplica seus commits por cima, mantendo o histórico linear (sem commits de merge desnecessários).
- `git push origin HEAD:<branch>` envia o commit atual (`HEAD`) explicitamente para a branch remota indicada, evitando subir para a branch errada.

## Conflitos no rebase

1. Resolver os arquivos marcados como em conflito.
2. `git add <arquivos resolvidos>`
3. `git rebase --continue`

Para desistir e voltar ao estado anterior: `git rebase --abort`.

Nunca usar `git push --force` em branch compartilhada.

## Mensagens de commit

- Frase curta, em português, no imperativo: `Documentar stack do piloto`, `Adicionar ingestão de OD`.
- Referenciar a issue relacionada no corpo: `Refs #18`. Use `Closes #18` quando o commit concluir a issue (ela fecha quando o commit chegar à branch padrão).
- Um assunto por commit.

## Levar a etapa para `develop` e `main`

Por Pull Request no GitHub (`etapa-N` → `develop` → `main`), com revisão de pelo menos um colega.
