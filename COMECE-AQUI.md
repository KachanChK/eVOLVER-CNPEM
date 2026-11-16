# Início rápido

O guia completo, com instalação, banco, simulador, testes e solução básica de problemas, está no [README principal](README.md).

Se as dependências, os arquivos `.env`, os contêineres e as migrações já estiverem preparados, execute na raiz:

```powershell
.\scripts\iniciar-local.ps1
```

O comando abre janelas separadas para API, ingestão e interface. Acompanhe a saída em cada janela e pressione Ctrl+C na janela de um serviço para interrompê-lo.

Abra http://127.0.0.1:5173, crie um experimento e execute em outro PowerShell:

```powershell
.\scripts\simular.ps1
```

Se a aplicação já estiver em execução, não é necessário iniciar os serviços novamente.
