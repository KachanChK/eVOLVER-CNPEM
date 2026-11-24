# Frontend

Interface Vue 3 para cadastro de experimentos, alocação de vials e histórico de
temperatura, pH e OD. Com Node.js 22.12 ou superior, execute `npm ci` e `npm run dev`.
O Vite encaminha `/api` à FastAPI local na porta 8000. Use `npm run build` para
verificar o build. O [README principal](../README.md) descreve o fluxo completo.

## Prévia 3D do simulador

Na barra lateral, em **Páginas do sistema**, abra **Prévia 3D** (`/simulador-3d`).
Arraste a maquete na horizontal ou use as setas com a maquete em foco.
Passe o mouse sobre um vial para ver seu número e o código do experimento alocado.
A prévia consulta as alocações da API. Quando a API está indisponível na abertura,
a tela indica que está exibindo estados de exemplo para os 12 vials.
