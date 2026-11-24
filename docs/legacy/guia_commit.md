# Como trabalhar com commits

## Branches

| Branch | Uso |
| --- | --- |
| `main` | Versão estável. Não recebe commits diretos. |
| `develop` | Integração das tarefas concluídas. Não recebe commits diretos. |
| `eN-tNN-descricao` | Branch de uma tarefa, criada a partir da `develop` atualizada (ex.: `e2-t03-separar-simulador`). |

## Fluxo

```bash
git switch develop
git pull --ff-only origin develop
git switch -c e2-t03-separar-simulador
git add <arquivos>
git commit -m "Mensagem do commit"
git push -u origin e2-t03-separar-simulador
```

- Cada tarefa usa uma branch própria criada a partir de `develop`.
- Novas correções do mesmo PR são enviadas como commits adicionais na mesma branch.
- Não faça commit nem push diretamente em `develop` ou `main`.

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

A branch da tarefa segue para `develop` por Pull Request e é removida após o merge.
Versões validadas seguem de `develop` para `main` por outro Pull Request.
