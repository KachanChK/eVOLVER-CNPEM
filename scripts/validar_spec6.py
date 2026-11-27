"""Exercise Spec 6 in a disposable stack and save browser, MQTT and DB evidence."""

import argparse
import contextlib
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4


def worker():
    from evolver_contracts.models import TelemetryEvent
    from evolver_simulator.config import SimulatorSettings
    from evolver_simulator.mqtt import MqttPublisher

    settings = SimulatorSettings()
    publisher = MqttPublisher(settings)
    publisher.connect()
    try:
        for sequence, line in enumerate(sys.stdin):
            request = json.loads(line)
            if "ports" in request:
                unreachable = []
                for port in request["ports"]:
                    try:
                        with socket.create_connection(("host.docker.internal", port), timeout=1):
                            pass
                    except OSError:
                        unreachable.append(port)
                print(json.dumps({"unreachable": unreachable}), flush=True)
                continue
            allocations = publisher.active_vials()
            if "od" not in request:
                print(json.dumps([
                    {"vial": allocation.vial_id, "on": publisher.pump_is_on(allocation)}
                    for allocation in allocations
                ]), flush=True)
                continue
            [allocation] = allocations
            event = TelemetryEvent(
                schema_version="1.0", event_id=uuid4(), producer_id=settings.producer_id,
                equipment_id=settings.equipment_id, vial_id=str(allocation.vial_id),
                experiment_run_id=str(allocation.allocation_id), measurement_type="od",
                value=request["od"], sequence=sequence,
                generated_at=datetime.now(UTC) - timedelta(seconds=request.get("delay", 0)),
            )
            publisher.publish(event)
            print(event.model_dump_json(), flush=True)
    finally:
        publisher.close()


def run(args):
    import httpx
    import paho.mqtt.client as mqtt
    from playwright.sync_api import expect, sync_playwright
    from sqlalchemy import create_engine, text

    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    name = "evolver-spec6-" + uuid4().hex[:8]
    broker = f"{name}-mosquitto-1"
    network = f"{name}-sim"
    volume = f"{name}-state"
    db = f"{name}-db"
    compose = (
        "docker", "compose", "-p", name, "--env-file", "mqtt/.env.example",
        "-f", "mqtt/compose.yaml",
    )
    env = {**os.environ, "MQTT_PORT": str(available_port()), "MQTT_BIND_HOST": "127.0.0.1"}
    password = "spec6-disposable-only"
    for user in ("HEALTH", "INGESTION", "API", "SIMULATOR"):
        env[f"MQTT_{user}_PASSWORD"] = password
    api_port, web_port = available_port(), available_port()

    def cmd(*command, check=True, **kwargs):
        return subprocess.run(
            command, cwd=root, env=env, check=check, encoding="utf-8", **kwargs
        )

    def published_port(container, port):
        return int(cmd("docker", "port", container, f"{port}/tcp", capture_output=True)
                   .stdout.strip().rsplit(":", 1)[1])

    def stop(process):
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=10)

    with (
        tempfile.TemporaryDirectory(prefix="evolver-spec6-") as folder,
        contextlib.ExitStack() as stack,
    ):
        temp = Path(folder)
        for package in ("simulator", "packages/contracts"):
            destination = temp / package
            shutil.copytree(root / package / "src", destination / "src",
                            ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copy2(root / package / "pyproject.toml", destination)
        shutil.copy2(__file__, temp / "driver.py")
        dockerfile = """FROM python:3.12-slim
WORKDIR /app
COPY packages/contracts packages/contracts
COPY simulator simulator
RUN pip install --no-cache-dir ./packages/contracts ./simulator
COPY driver.py .
"""
        image = f"{name}-simulator:test"
        cmd("docker", "build", "-f", "-", "-t", image, str(temp), input=dockerfile)
        stack.callback(cmd, "docker", "image", "rm", image, check=False)

        cmd("docker", "run", "-d", "--rm", "--name", db, "-e", f"POSTGRES_PASSWORD={password}",
            "-e", "POSTGRES_DB=evolver_test_spec6", "-p", "127.0.0.1:0:5432",
            "timescale/timescaledb:2.31.0-pg17")
        stack.callback(cmd, "docker", "stop", db, check=False)
        db_port = published_port(db, 5432)
        database = f"postgresql+psycopg://postgres:{password}@127.0.0.1:{db_port}/evolver_test_spec6"
        env["DATABASE_URL"] = database
        engine = create_engine(database)
        stack.callback(engine.dispose)

        def database_ready():
            from sqlalchemy.exc import OperationalError

            try:
                with engine.connect() as connection:
                    return connection.scalar(text("SELECT 1"))
            except OperationalError:
                return False

        try:
            wait_for(database_ready, "TimescaleDB", timeout=90)
        except TimeoutError:
            cmd("docker", "logs", db, check=False)
            raise
        cmd(sys.executable, "-m", "alembic", "-c", "backend/alembic.ini", "upgrade", "head")

        cmd("docker", "network", "create", "--internal", network)
        stack.callback(cmd, "docker", "network", "rm", network, check=False)
        stack.callback(cmd, *compose, "down", "-v", check=False)
        cmd(*compose, "up", "-d", "--wait")
        mqtt_port = published_port(broker, 1883)
        cmd("docker", "network", "connect", "--alias", "broker", network, broker)
        cmd("docker", "volume", "create", volume)
        stack.callback(cmd, "docker", "volume", "rm", volume, check=False)
        env.update(MQTT_HOST="127.0.0.1", MQTT_PORT=str(mqtt_port))

        def background(label, *command, **kwargs):
            log = stack.enter_context((output / f"{label}.log").open("w", encoding="utf-8"))
            process = subprocess.Popen(
                command, cwd=root, env=env, stderr=log,
                stdout=kwargs.pop("stdout", log), **kwargs,
            )
            stack.callback(stop, process)
            return process

        background("ingestao", sys.executable, "-m", "evolver.ingestion")
        background("api", sys.executable, "-m", "uvicorn", "evolver.api.main:app",
                   "--host", "127.0.0.1", "--port", str(api_port))
        config = temp / "vite.config.mjs"
        config.write_text(
            'export default { preview: { proxy: { "/api": '
            f'"http://127.0.0.1:{api_port}" }} }} }}',
            encoding="utf-8",
        )
        background("frontend", "node", "frontend/node_modules/vite/bin/vite.js", "preview",
                   "frontend", "--configLoader", "native", "--config", str(config), "--strictPort",
                   "--host", "127.0.0.1", "--port", str(web_port))

        wire = []
        wire_ready = threading.Event()
        subscriber = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=f"{name}-evidence")
        subscriber.username_pw_set("evolver-ingestion", password)
        subscriber.on_connect = lambda client, *_: client.subscribe(
            "evolver/v1/evolver-sim-01/command-results", qos=1
        )
        subscriber.on_message = lambda _client, _userdata, message: wire.append(
            json.loads(message.payload)
        )
        subscriber.on_subscribe = lambda *_: wire_ready.set()
        subscriber.connect("127.0.0.1", mqtt_port)
        subscriber.loop_start()
        stack.callback(subscriber.loop_stop)
        stack.callback(subscriber.disconnect)

        def ingestion_sessions():
            return (output / "ingestao.log").read_bytes().count(b"pronta para telemetria")

        wait_for(ingestion_sessions, "assinatura inicial da ingestão")
        assert wire_ready.wait(timeout=15)

        def simulator(label, *command, interactive=False):
            container = f"{name}-{label}"
            stack.callback(cmd, "docker", "rm", "-f", container, check=False,
                           capture_output=True)
            return background(
                label, "docker", "run", "-i", "--rm", "--name", container, "--network", network,
                "-v", f"{volume}:/state", "-e", "MQTT_HOST=broker", "-e", "MQTT_PORT=1883",
                "-e", f"MQTT_SIMULATOR_PASSWORD={password}",
                "-e", "SIMULATOR_PUMP_STATE_PATH=/state/pump.sqlite3",
                "-e", "SIMULATOR_SEED=42", "-e", "SIMULATOR_OD_NOISE=0",
                image, "python", *command,
                **({"stdin": subprocess.PIPE, "stdout": subprocess.PIPE, "text": True}
                   if interactive else {}),
            )

        def ask(process, **payload):
            process.stdin.write(json.dumps(payload) + "\n")
            process.stdin.flush()
            return json.loads(process.stdout.readline())

        client = stack.enter_context(httpx.Client(base_url=f"http://127.0.0.1:{web_port}"))

        def api(path):
            response = client.get("/api" + path)
            response.raise_for_status()
            return response.json()

        def web_ready():
            try:
                return client.get("/api/experiments").status_code == 200
            except httpx.HTTPError:
                return False

        wait_for(web_ready, "Vite e API")
        browser_factory = stack.enter_context(sync_playwright())
        browser = browser_factory.chromium.launch(channel=args.browser_channel)
        stack.callback(browser.close)
        page = browser.new_page(viewport={"width": 1440, "height": 1000},
                                locale="pt-BR", timezone_id="America/Sao_Paulo")
        page.set_default_timeout(15_000)
        expect.set_options(timeout=15_000)
        page.on("dialog", lambda dialog: dialog.accept())
        page.goto(str(client.base_url))
        page.get_by_role("button", name="Criar experimento").click()
        dialog = page.get_by_role("dialog")
        dialog.get_by_label("Nome").fill("Aceite Spec 6")
        dialog.get_by_label("Tipo de cultura").fill("Ensaio simulado")
        dialog.get_by_label("Vial").select_option("1")
        assert dialog.locator("select").count() == 1
        dialog.get_by_role("button", name="Criar experimento").click()
        expect(dialog.get_by_text("Informe este limite de OD.", exact=True)).to_have_count(2)
        dialog.get_by_label("OD mínima").fill("0,09")
        expect(dialog.get_by_text("Informe um valor entre 0,10 e 0,80.")).to_be_visible()
        dialog.get_by_label("OD mínima").fill("0,30")
        dialog.get_by_label("OD máxima").fill("0,29")
        expect(dialog.get_by_text("Informe um valor maior que a OD mínima.")).to_be_visible()
        page.screenshot(path=output / "00-cadastro.jpg", quality=82)
        dialog.get_by_label("OD máxima").fill("0,40")
        dialog.get_by_role("button", name="Criar experimento").click()
        expect(dialog).to_be_hidden()
        expect(page.get_by_role("heading", name="Aceite Spec 6")).to_be_visible()
        [experiment] = api("/experiments")
        experiment_id = experiment["id"]
        base = f"/experiments/{experiment_id}"
        summary = page.locator(".pump-summary")
        scenarios = {}

        def snapshot():
            return api(base + "/pump/snapshot")

        def state():
            return snapshot()["pump"]

        def history():
            return snapshot()["history"]

        def at_pump(mode, confirmed):
            return wait_for(
                lambda: (snapshot := state())["state"] == mode
                and snapshot["confirmed_state"] == confirmed and not snapshot["pending_command_id"],
                f"{mode}/{confirmed}",
            )

        def matching_panel(current):
            fields = {}

            def check(label, description, date=None, command_id=None, *, od=False):
                term = summary.get_by_text(label, exact=True)
                value = term.locator("xpath=following-sibling::dd")
                if od:
                    expect(value.locator("strong")).to_have_text(description)
                else:
                    expect(value).to_contain_text(description)
                details = {}
                if date:
                    time_element = value.locator("time")
                    expect(time_element).to_have_attribute("datetime", date)
                    rendered_time = page.evaluate("""value =>
                        new Intl.DateTimeFormat('pt-BR', {
                            dateStyle: 'short', timeStyle: 'medium'
                        }).format(new Date(value))
                    """, date)
                    expect(time_element).to_have_text(rendered_time)
                    details["datetime"] = time_element.get_attribute("datetime")
                if command_id:
                    if label == "Comando pendente":
                        expect(value.locator("code")).to_have_text(command_id)
                    else:
                        expect(value).to_have_attribute("data-command-id", command_id)
                    details["command_id"] = command_id
                details["text"] = value.inner_text()
                fields[label] = details

            latest = current["latest_od"]
            if latest:
                formatted = f'{latest["value"]:.6f}'.rstrip("0").rstrip(".").replace(".", ",")
                check("Última OD", formatted, latest["generated_at"], od=True)
                chart = page.get_by_role("region", name="Densidade óptica (OD)", exact=True)
                expect(chart.locator(".latest strong")).to_have_text(formatted)
                chart_latest = chart.locator(".latest span")
                expect(chart_latest).to_contain_text(fields["Última OD"]["text"].splitlines()[1])
                fields["Último valor no gráfico de OD"] = {
                    "text": chart.locator(".latest strong").inner_text() + "\n"
                    + chart_latest.inner_text(),
                    "datetime": latest["generated_at"],
                }
            else:
                check("Última OD", "Sem medições")
            pump = current["pump"]
            check("Estado das bombas", {
                "on": "Bombas ligadas (simuladas)", "off": "Bombas desligadas (simuladas)", "unknown": "Desconhecido",
            }[pump["confirmed_state"]])
            mode = "Encerrado" if current["ended_at"] else (
                "Pausado para encerrar" if pump["ending"] else {
                    "automatic": "Bombas em modo automático", "paused": "Bombas pausadas",
                    "pausing": "Pausando…",
                }[pump["state"]]
            )
            check("Modo de controle", mode)
            commands = current["history"]["commands"]
            status = {"pending": "Aguardando resultado", "received": "Recebido pelo simulador",
                      "executed": "Executado no simulador"}

            def command_label(command):
                action = "Ligar bombas" if command["desired_state"] == "on" else "Desligar bombas"
                return f'{action} · {status[command["result_status"]]}'

            if pending_id := pump["pending_command_id"]:
                pending = next(c for c in commands if c["command_id"] == pending_id)
                check("Comando pendente", command_label(pending), command_id=pending_id)
            else:
                check("Comando pendente", "Nenhum")
            transition = current["history"]["transitions"][-1]
            check("Última mudança", {
                "initial": "Início da alocação",
                "od_min": "OD atingiu ou ficou abaixo do limite mínimo",
                "od_max": "OD atingiu ou superou o limite máximo", "pause": "Pausa solicitada",
                "resume": "Retomada solicitada", "ending": "Encerramento solicitado",
                "reconcile": "Reconciliação do estado das bombas",
                "confirmation_lost": "Confirmação perdida ou indisponível",
            }[transition["reason"]], transition["observed_at"])
            results = [c for c in commands if c["result_status"] not in ("pending", "received")]
            if results:
                latest_result = max(
                    reversed(results), key=lambda c: datetime.fromisoformat(c["result_at"]),
                )
                check("Último resultado registrado", command_label(latest_result),
                      latest_result["result_at"], latest_result["command_id"])
            else:
                check("Último resultado registrado", "Sem resultado registrado")
            return fields

        def capture(label, *, input_event=None, extra=None):
            current = snapshot()
            rendered = matching_panel(current)
            with engine.connect() as connection:
                connection.execution_options(isolation_level="REPEATABLE READ")
                readings = connection.execute(text("""
                    SELECT event_id, od_value, generated_at, received_at, sequence,
                           allocation_verified
                    FROM od_readings WHERE experiment_id = :id
                    ORDER BY generated_at DESC, event_id DESC LIMIT 4
                """), {"id": experiment_id}).mappings()
                control = connection.execute(text("""
                    SELECT e.id, e.allocation_id, e.ended_at, c.paused, c.resume_pending,
                           c.confirmed_state, c.desired_state, c.pending_command_id,
                           c.last_event_id, c.reconcile_required, c.ending
                    FROM experiments e JOIN pump_control c ON c.experiment_id = e.id
                    WHERE e.id = :id
                """), {"id": experiment_id}).mappings().one()
                commands = connection.execute(text("""
                    SELECT p.command_id, p.reason, p.desired_state, p.created_at, p.sent_at,
                           p.puback_at, p.result_status, p.result_at, p.result_detail,
                           p.reading_event_id, od.od_value AS trigger_od
                    FROM pump_commands p LEFT JOIN od_readings od
                      ON od.event_id = p.reading_event_id AND od.experiment_id = p.experiment_id
                    WHERE p.experiment_id = :id ORDER BY p.created_at
                """), {"id": experiment_id}).mappings()
                transition = connection.execute(text("""
                    SELECT observed_at, paused, confirmed_state, reason, command_id
                    FROM pump_transitions WHERE experiment_id = :id ORDER BY id DESC LIMIT 1
                """), {"id": experiment_id}).mappings().one()
                data = {"control": dict(control), "od": [dict(row) for row in readings],
                        "commands": [dict(row) for row in commands], "transition": dict(transition)}
                if input_event:
                    params = {"id": experiment_id, "event_id": input_event["event_id"]}
                    row = connection.execute(text("""
                        SELECT event_id, od_value, generated_at, received_at, allocation_verified
                        FROM od_readings WHERE experiment_id = :id AND event_id = :event_id
                    """), params).mappings().one()
                    data["input_od"] = dict(row)
            pump = current["pump"]
            assert data["control"]["confirmed_state"] == pump["confirmed_state"]
            assert data["control"]["ending"] == pump["ending"]
            pending_id = data["control"]["pending_command_id"]
            assert (str(pending_id) if pending_id else None) == pump["pending_command_id"]
            observed = current["history"]["transitions"][-1]
            assert transition["reason"] == observed["reason"]
            assert transition["observed_at"] == datetime.fromisoformat(observed["observed_at"])
            assert transition["paused"] == observed["paused"]
            assert [(str(c["command_id"]), c["result_status"]) for c in data["commands"]] == [
                (c["command_id"], c["result_status"]) for c in current["history"]["commands"]
            ]
            latest = current["latest_od"]
            if latest:
                assert str(data["od"][0]["event_id"]) == latest["event_id"]
                assert data["od"][0]["od_value"] == latest["value"]
                generated_at = datetime.fromisoformat(latest["generated_at"])
                assert data["od"][0]["generated_at"] == generated_at
            else:
                assert not data["od"]
            scenarios[label] = {
                "input": input_event, "extra": extra, "database": data,
                "api_pump": current["pump"], "api_history": current["history"],
                "api_latest_od": latest, "api_ended_at": current["ended_at"],
                "rendered_fields": rendered,
                "rendered_summary": summary.inner_text(),
            }
            save_json(output / "cenarios.json", scenarios)
            page.screenshot(path=output / f"{label}.jpg", quality=82, full_page=True)
            print(f"Capturado: {label}", flush=True)

        expect(summary.get_by_text("Bombas desligadas (simuladas)", exact=True)).to_be_visible()
        capture("01-criacao")

        cycles = simulator("simulador-ciclos", "-m", "evolver_simulator")

        def reported_cycles():
            if cycles.poll() is not None:
                raise RuntimeError("O produtor de OD terminou antes do segundo ciclo.")
            commands = history()["commands"]
            if len(commands) >= 4 and commands[3]["result_status"] not in ("pending", "received"):
                return commands
            return None

        commands = wait_for(reported_cycles, "dois ciclos do simulador", timeout=60)
        assert [(c["reason"], c["result_status"]) for c in commands[:4]] == [
            ("od_max", "executed"), ("od_min", "executed"),
            ("od_max", "executed"), ("od_min", "executed"),
        ], commands
        cmd("docker", "stop", "--time", "8", f"{name}-simulador-ciclos")
        assert cycles.wait(timeout=15) == 0
        page.get_by_role("button", name="Tudo", exact=True).click()
        expect(page.get_by_text("Ver períodos e comandos das bombas", exact=True)).to_have_count(0)
        capture("02-dois-ciclos")

        sim = simulator("simulador-controlado", "driver.py", "--worker", interactive=True)
        ports = [api_port, db_port]
        topology = ask(sim, ports=ports)
        assert topology["unreachable"] == ports
        assert ask(sim)[0]["vial"] == 1
        save_json(output / "topologia.json", {
            "network": json.loads(cmd("docker", "network", "inspect", network, capture_output=True)
                                  .stdout)[0]["Internal"],
            "broker_from_simulator": "broker:1883",
            "unreachable_monitor": topology["unreachable"],
            "api_port": api_port, "db_port": db_port, "broker_host_port": mqtt_port,
        })

        def sample(od, **parameters):
            event = ask(sim, od=od, **parameters)
            wait_for(lambda: any(
                row["event_id"] == event["event_id"] for row in api(base + "/readings/od")
            ), "OD persistida via MQTT")
            return event

        sample(0.35)
        at_pump("automatic", "off")
        high = sample(0.40)
        at_pump("automatic", "on")
        expect(summary.get_by_text("Bombas ligadas (simuladas)", exact=True)).to_be_visible()
        cmd("docker", "pause", f"{name}-simulador-controlado")
        try:
            page.get_by_role("button", name="Pausar bombas").click()
            pending = wait_for(lambda: state()["pending_command_id"], "intenção de desligar")
            expect(summary.get_by_text(pending, exact=True)).to_be_visible()
            assert state()["confirmed_state"] == "on"
            capture("03a-desligamento-pendente", input_event=high)
        finally:
            cmd("docker", "unpause", f"{name}-simulador-controlado")
        at_pump("paused", "off")
        expect(summary.get_by_text("Bombas pausadas", exact=True)).to_be_visible()
        capture("03-pausa-ligada", input_event=high)

        below = sample(0.35)
        count = len(history()["commands"])
        page.get_by_role("button", name="Despausar bombas").click()
        at_pump("automatic", "off")
        expect(summary.get_by_text("Bombas em modo automático", exact=True)).to_be_visible()
        assert len(history()["commands"]) == count
        capture("04-retomada-abaixo", input_event=below)

        page.get_by_role("button", name="Pausar bombas").click()
        at_pump("paused", "off")
        expect(summary.get_by_text("Bombas pausadas", exact=True)).to_be_visible()
        assert len(history()["commands"]) == count
        capture("05-pausa-desligada")

        maximum = sample(0.40)
        page.get_by_role("button", name="Despausar bombas").click()
        at_pump("automatic", "on")
        expect(summary.get_by_text("Bombas ligadas (simuladas)", exact=True)).to_be_visible()
        assert history()["commands"][-1]["reason"] == "resume"
        capture("06-retomada-no-maximo", input_event=maximum)

        delayed = sample(0.10, delay=12)
        assert state()["confirmed_state"] == "on"
        assert api(base + "/readings/od")[-1]["event_id"] == maximum["event_id"]
        assert history()["commands"][-1]["reading_event_id"] == maximum["event_id"]
        capture("07-leitura-atrasada", input_event=delayed)

        assert ask(sim)[0]["on"]
        sim.stdin.close()
        assert sim.wait(timeout=15) == 0
        cmd("docker", "stop", broker)
        expect(summary.get_by_text("Leitura antiga", exact=True)).to_be_visible(timeout=20_000)
        expect(summary.get_by_text("Resultado antigo", exact=True)).to_be_visible(timeout=20_000)
        capture("08-desconexao")
        sessions_before_restart = ingestion_sessions()
        wire_ready.clear()
        cmd("docker", "start", broker)
        wait_for(lambda: ingestion_sessions() > sessions_before_restart, "reconexão da ingestão")
        assert wire_ready.wait(timeout=15)
        at_pump("automatic", "unknown")
        expect(summary.get_by_text("Desconhecido", exact=True)).to_be_visible()
        capture("09-reconexao-sem-confirmacao")

        sim = simulator("simulador-reiniciado", "driver.py", "--worker", interactive=True)
        preserved = ask(sim)
        assert preserved[0]["on"]
        fresh = sample(0.35)
        at_pump("automatic", "off")
        expect(summary.get_by_text("Bombas desligadas (simuladas)", exact=True)).to_be_visible()
        assert history()["commands"][-1]["reason"] == "reconcile"
        capture("10-reinicio", input_event=fresh, extra={"sqlite_before_reconcile": preserved})

        high = sample(0.40)
        at_pump("automatic", "on")
        page.get_by_role("button", name="Inativar", exact=True).click()
        expect(summary.get_by_text("Encerrado", exact=True)).to_be_visible()
        assert api(base)["ended_at"] is not None
        assert state()["confirmed_state"] == "off"
        assert history()["commands"][-1]["reason"] == "ending"
        assert any(vial["vial_id"] == 1 for vial in api("/vials/available"))
        capture("11-encerramento", input_event=high)

        results = {(entry["command_id"], entry["status"]) for entry in wire}
        for command in history()["commands"]:
            for status in ("received", "executed"):
                assert (command["command_id"], status) in results, command
        save_json(output / "resultados-mqtt.json", wire)


def save_json(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, default=str, indent=2), encoding="utf-8")


def available_port():
    with socket.socket() as candidate:
        candidate.bind(("127.0.0.1", 0))
        return candidate.getsockname()[1]


def wait_for(condition, label, timeout=20):
    until = time.monotonic() + timeout
    while time.monotonic() < until:
        if result := condition():
            return result
        time.sleep(0.15)
    raise TimeoutError(label)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--output", type=Path, default=Path(".local/spec6-ensaio"))
    parser.add_argument("--browser-channel", default="msedge")
    arguments = parser.parse_args()
    if arguments.worker:
        worker()
    else:
        run(arguments)
