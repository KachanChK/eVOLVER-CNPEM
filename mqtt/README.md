# Serviço MQTT independente

Esta pasta contém o broker Mosquitto local. Ele possui Compose, configuração,
credenciais, ACL, persistência e verificações próprios e não depende do backend nem
do banco.

## Início rápido

No PowerShell, a partir desta pasta:

```powershell
Copy-Item .env.example .env
docker compose config --quiet
docker compose up -d
docker compose ps
docker compose exec mosquitto sh /mosquitto/config/smoke-test.sh
```

O serviço deve aparecer como `healthy`. Para pará-lo sem apagar o volume:

```powershell
docker compose down
```

Não use `docker compose down -v` como rotina, pois `-v` apaga a persistência local
do broker.

O roteiro completo para observar uma temperatura saindo do simulador e chegando a
um assinante está em [plano-mqtt-independente.md](../docs/plano-mqtt-independente.md).
