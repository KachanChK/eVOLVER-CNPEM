# Como trabalhar com commits

## Branches

| Branch | Uso |
| --- | --- |
| `main` | Versão estável. Não recebe commits diretos. |
| `develop` | Integração das etapas concluídas. Não recebe commits diretos. |
| `etapa-N` | Branch de trabalho da etapa ou funcionalidade em andamento (ex.: `etapa-1`). **Os commits são todos feitos aqui.** |

## Fluxo

```bash
git checkout etapa-1
git add <arquivos>
git commit -m "Mensagem do commit"
git pull --rebase origin etapa-1
git push origin HEAD:etapa-1
```

- `git pull --rebase` atualiza a árvore local antes do envio.
- `git push origin HEAD:<branch>` envia o commit atual para a branch remota indicada.

## Conflitos no rebase

```bash
git add <arquivos resolvidos>
git rebase --continue
```

`git rebase --abort` cancela o rebase. `git push --force` não é usado.

## Observações

- Na mensagem do commit: frase curta, em português, iniciada por um verbo no infinitivo. Ela deve completar naturalmente a frase: **"Se aplicado, este commit irá {mensagem do commit}"**. Exemplo: `Revisar a documentação da stack local (Refs #18)`.
- Caso esteja trabalhando em uma issue, sempre faça referência à issue no commit: `Refs #N` ou `Closes #N`.

## Integração

A branch da etapa segue para `develop` e depois para `main` por Pull Request.
