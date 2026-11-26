"""Tkinter window for exercising the live simulator scenarios."""

from concurrent.futures import ThreadPoolExecutor

from .runner import SimulatorRunner
from .scenarios import SCENARIO_LABELS, Scenarios


class TestCenterError(RuntimeError):
    pass


def run_with_center(runner: SimulatorRunner, scenarios: Scenarios, max_messages: int | None) -> int:
    try:
        import tkinter as tk
        from tkinter import ttk
    except ImportError as exc:
        raise TestCenterError(
            "Tkinter indisponível. Use --headless para executar sem janela.",
        ) from exc

    try:
        root = tk.Tk()
    except tk.TclError as exc:
        raise TestCenterError(f"Não foi possível abrir a Central de testes: {exc}") from exc
    root.title("Central de testes — eVOLVER")
    root.minsize(420, 0)
    frame = ttk.Frame(root, padding=18)
    frame.grid(sticky="nsew")
    root.columnconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    ttk.Label(frame, text="Experimento e vial").grid(sticky="w")
    choices = ttk.Combobox(frame, state="readonly")
    choices.grid(sticky="ew", pady=(4, 12))
    available = ()
    buttons = []

    def start(kind: str) -> None:
        index = choices.current()
        if index >= 0:
            scenarios.start(kind, available[index][0])
            refresh()

    for kind, label in SCENARIO_LABELS.items():
        button = ttk.Button(frame, text=label, command=lambda kind=kind: start(kind))
        button.grid(sticky="ew", pady=2)
        buttons.append(button)
    status = tk.StringVar()
    ttk.Label(frame, textvariable=status, wraplength=380).grid(sticky="w", pady=(12, 0))

    def refresh() -> None:
        nonlocal available
        vials, active, message = scenarios.snapshot()
        options = tuple((
            str(vial.allocation_id),
            f"Vial {vial.vial_id} · {vial.experiment_name or f'Experimento {vial.experiment_id}'}",
        ) for vial in vials)
        if available != options:
            selected = choices.current()
            previous = available[selected][0] if selected >= 0 else None
            available = options
            choices["values"] = [label for _, label in available]
            if available:
                selected = next((i for i, (id_, _) in enumerate(available) if id_ == previous), 0)
                choices.current(selected)
            else:
                choices.set("")
        choices.configure(state="disabled" if active or not available else "readonly")
        for button in buttons:
            button.state(["disabled" if active or not available else "!disabled"])
        if status.get() != message:
            status.set(message)

    # Keep the Tk loop alive after closing the window, so Ctrl+C still works.
    root.protocol("WM_DELETE_WINDOW", root.withdraw)
    with ThreadPoolExecutor(max_workers=1) as collector:
        result = collector.submit(runner.run, max_messages=max_messages)

        def tick() -> None:
            if result.done():
                root.destroy()
            else:
                refresh()
                root.after(200, tick)

        try:
            root.after(0, tick)
            root.mainloop()
        finally:
            runner.stop()
        return result.result()
