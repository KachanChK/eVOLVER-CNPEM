# Instruções de commit

## Branches

- `main` e `develop` não recebem commits diretos.
- Os commits são feitos na branch da etapa ou feature em andamento (ex.: `etapa-1`).

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

## Mensagem

- Frase curta, em português, no imperativo.
- Referência à issue no corpo: `Refs #N` ou `Closes #N`.

## Integração

A branch da etapa segue para `develop` e depois para `main` por Pull Request.
