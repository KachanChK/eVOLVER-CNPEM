# MQTT independente e simulador mínimo de temperatura

## Objetivo

Executar o Mosquitto como serviço independente do backend, do banco e dos demais
componentes. Nesta primeira versão, um pequeno simulador Python publica uma única
temperatura e um assinante de teste mostra a mensagem recebida.

```text
Simulador Python (Paho MQTT) -> Mosquitto -> assinante mosquitto_sub
```

Tudo roda inicialmente na mesma máquina e se comunica por `127.0.0.1:1883`. O broker
pode ser iniciado e encerrado sem iniciar backend ou banco.

## Conceitos usados

- **Docker Compose:** lê o `compose.yaml` e inicia o contêiner do Mosquitto com sua
  porta, arquivos, credenciais, volume e healthcheck.
- **Mosquitto:** broker, isto é, o servidor central que recebe publicações e as
  encaminha para os clientes interessados.
- **Paho MQTT:** biblioteca usada pelo simulador Python para se conectar ao broker.
- **Tópico:** endereço lógico de uma mensagem. O teste usa
  `evolver/dev/evolver-sim-01/telemetry`.
- **Publicar:** enviar uma mensagem para um tópico.
- **Assinar:** pedir ao broker as próximas mensagens de um tópico. O `+` em
  `evolver/dev/+/telemetry` aceita qualquer equipamento naquele nível.
- **Autenticação:** cada cliente apresenta usuário e senha ao se conectar.
- **ACL:** lista que limita os tópicos que cada usuário pode publicar ou assinar.
- **QoS 1:** o publicador tenta entregar a mensagem pelo menos uma vez e espera uma
  confirmação; uma repetição é possível se a confirmação se perder.
- **PUBACK:** confirmação do Mosquitto de que recebeu a publicação QoS 1. Não prova
  processamento por outro cliente nem gravação em banco.
- **Smoke test:** script curto que confere autenticação, ACL, publicação, assinatura
  e ausência de mensagens retidas.

## Estrutura e comportamento

`mqtt/` contém todo o serviço Mosquitto: Compose, `.env`, configuração, ACL,
entrypoint e smoke test. `simulator/` é um projeto Python separado e só conhece o
endereço e a credencial de seu cliente MQTT. O backend não contém nem inicia o
broker.

O simulador publica uma vez, com MQTT 5, QoS 1 e `retain=false`:

```json
{
  "equipment_id": "evolver-sim-01",
  "measurement": "temperature",
  "value": 37.0,
  "unit": "celsius",
  "generated_at": "<horário UTC em ISO 8601>"
}
```

O tópico `evolver/dev/...` é temporário porque este teste ainda não usa os schemas
oficiais de `evolver/v1/...`.

## Pré-requisitos

Instale apenas:

1. Docker Desktop com Docker Compose v2.
2. `uv`, que instala a dependência Paho MQTT e obtém o Python 3.12 quando necessário.

No Windows, se ainda não estiverem instalados:

```powershell
winget install --id Docker.DockerDesktop
winget install --id astral-sh.uv
```

Depois da instalação, abra o Docker Desktop, espere aparecer `Engine running` e
reabra o PowerShell para atualizar o `PATH`.

Confira no PowerShell:

```powershell
docker --version
docker compose version
uv --version
```

Não é necessário instalar Mosquitto, `mosquitto_pub`, `mosquitto_sub`, Paho MQTT ou
Python manualmente. O Docker fornece o broker e seus clientes; o `uv` prepara o
simulador.

## Preparar a configuração

Na raiz do repositório:

```powershell
Copy-Item mqtt/.env.example mqtt/.env
Copy-Item simulator/.env.example simulator/.env
```

`MQTT_SIMULATOR_PASSWORD` deve ter o mesmo valor nos dois arquivos. Os exemplos já
estão alinhados para desenvolvimento local.

## Iniciar e verificar o MQTT

```powershell
Set-Location mqtt
docker compose config --quiet
docker compose up -d
docker compose ps
docker compose exec mosquitto sh /mosquitto/config/smoke-test.sh
```

O contêiner deve aparecer como `healthy` e o script deve terminar com `Todas as
verificações passaram.`

## Observar a mensagem chegando

Abra dois terminais. O assinante precisa estar aberto antes da publicação porque o
broker não guarda mensagens retidas.

No **terminal A**, dentro de `mqtt/`, inicie o assinante:

```powershell
docker compose exec mosquitto sh -c 'mosquitto_sub -V mqttv5 -h 127.0.0.1 -u evolver-ingestion -P "$MQTT_INGESTION_PASSWORD" -t "evolver/dev/+/telemetry" -q 1 -v'
```

No **terminal B**, dentro de `simulator/`, prepare e execute o simulador:

```powershell
uv sync
uv run --env-file .env python -m evolver_simulator
```

O terminal B mostra a conexão, o JSON enviado e o PUBACK. O terminal A mostra uma
linha semelhante a:

```text
evolver/dev/evolver-sim-01/telemetry {"equipment_id":"evolver-sim-01","measurement":"temperature","value":37.0,"unit":"celsius","generated_at":"...Z"}
```

Encerre o assinante com `Ctrl+C`.

## Falha esperada e encerramento

Se o broker estiver desligado, o simulador deve encerrar com código diferente de
zero e informar que não conseguiu publicar. Para desligar somente o MQTT, dentro de
`mqtt/`:

```powershell
docker compose down
```

Não use `-v`, pois essa opção apaga o volume persistente do broker.

## Fora desta entrega

Não fazem parte deste teste: backend, ingestão, banco, fila SQLite, contratos
oficiais, envio contínuo, comandos de bomba, ACK após gravação, TLS e frontend.
