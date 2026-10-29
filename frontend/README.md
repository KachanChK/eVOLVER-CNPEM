# Frontend

Diretório reservado para a interface Vue 3 + Vite prevista na arquitetura.

A E2-T03 não cria uma aplicação frontend funcional, `package.json` nem lock de
dependências. A interface será implementada em task posterior e deverá acessar
somente a API Python por HTTP/SSE, nunca o PostgreSQL ou o broker MQTT diretamente.

Quando o projeto Vue for criado, deve usar Node.js 22.12 ou superior na linha 22,
registrar a versão em `.nvmrc` e `engines`, e versionar `package-lock.json`.
