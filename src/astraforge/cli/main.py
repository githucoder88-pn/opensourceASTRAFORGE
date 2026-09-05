"""``astraforge`` command line interface."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import typer
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from astraforge import __version__
from astraforge.core.approvals import AutoApproveGate, ConsoleGate, DenyAllGate
from astraforge.core.config import CONFIG_FILENAME, Config, ConfigError
from astraforge.core.factory import build_engine, make_goal
from astraforge.events.bus import JsonlEventSink
from astraforge.execution.engine import RunResult
from astraforge.models.core import Artifact, RunStatus, TaskStatus
from astraforge.planning.base import PlanningError
from astraforge.reporting.report import summarise
from astraforge.security.sandbox import describe_isolation, probe_support
from astraforge.security.workspace import Workspace
from astraforge.storage.run_store import RunStore
from astraforge.tools import default_registry
from astraforge.verification import default_verifiers

app = typer.Typer(
    name="astraforge",
    help=(
        "Open-source infrastructure for reliable AI work.\n\n"
        "Give AstraForge a goal. It plans the work, executes it through tools, "
        "verifies the result with evidence, and produces an auditable report."
    ),
    no_args_is_help=True,
    add_completion=False,
)
console = Console()

_TASK_STYLE = {
    TaskStatus.COMPLETED: "green",
    TaskStatus.FAILED: "red",
    TaskStatus.BLOCKED: "yellow",
    TaskStatus.CANCELLED: "dim",
}


def _fail(message: str, code: int = 1) -> None:
    console.print(f"[bold red]error[/] {message}")
    raise typer.Exit(code)


def _load_config(path: Path | None) -> Config:
    try:
        return Config.load(path)
    except ConfigError as exc:
        _fail(str(exc), code=2)
        raise  # pragma: no cover - _fail always exits


def _store(config: Config) -> RunStore:
    return RunStore(config.storage_dir)


def _resolve(store: RunStore, run_id: str) -> str:
    try:
        return store.resolve(run_id)
    except (FileNotFoundError, ValueError) as exc:
        _fail(str(exc), code=3)
        raise  # pragma: no cover


@app.callback(invoke_without_command=True)
def _root(
    ctx: typer.Context,
    version: bool = typer.Option(
        False, "--version", "-V", help="Show the version and exit."
    ),
) -> None:
    if version:
        console.print(f"astraforge {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        console.print(ctx.get_help())
        raise typer.Exit()


# --------------------------------------------------------------------------- #
# init
# --------------------------------------------------------------------------- #


@app.command()
def init(
    directory: Path = typer.Argument(Path("."), help="Project directory."),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing config."),
) -> None:
    """Create an astraforge.yaml file with commented, safe defaults."""
    directory.mkdir(parents=True, exist_ok=True)
    target = directory / CONFIG_FILENAME
    if target.exists() and not force:
        _fail(f"{target} already exists (use --force to overwrite)")

    config = Config(project=directory.resolve().name)
    header = (
        "# AstraForge configuration.\n"
        "# Secrets are never stored here - only the NAME of the env var to read.\n"
        "# Provider `echo` is deterministic and offline; switch to `openai`\n"
        "# (and set model.name / model.api_key_env) to use a real model.\n"
    )
    target.write_text(header + config.to_yaml(), encoding="utf-8")
    gitignore = directory / ".gitignore"
    entry = f"{config.storage_dir}/\n"
    if not gitignore.exists() or entry not in gitignore.read_text(encoding="utf-8"):
        with gitignore.open("a", encoding="utf-8") as fh:
            fh.write(entry)

    console.print(f"[green]created[/] {target}")
    console.print(f"[green]ignoring[/] {config.storage_dir}/ in .gitignore")
    console.print('\nNext: [bold]astraforge run "your goal here"[/]')


# --------------------------------------------------------------------------- #
# run
# --------------------------------------------------------------------------- #


@app.command()
def run(
    goal: str = typer.Argument(..., help="The goal to accomplish, in plain language."),
    config_path: Path | None = typer.Option(
        None, "--config", "-c", help=f"Path to {CONFIG_FILENAME}."
    ),
    plan_file: Path | None = typer.Option(
        None, "--plan", help="Execute a pre-authored plan file (JSON or YAML)."
    ),
    planner: str | None = typer.Option(
        None, "--planner", help="Override the planner: heuristic | model | static."
    ),
    provider: str | None = typer.Option(
        None, "--provider", help="Override the model provider (e.g. echo, openai)."
    ),
    model: str | None = typer.Option(None, "--model", help="Override the model name."),
    constraint: list[str] = typer.Option(
        [], "--constraint", help="A constraint the solution must respect (repeatable)."
    ),
    criterion: list[str] = typer.Option(
        [], "--criterion", help="A success criterion (repeatable)."
    ),
    yes: bool = typer.Option(
        False, "--yes", "-y", help="Auto-approve gated actions (unattended runs)."
    ),
    no_approve: bool = typer.Option(
        False, "--no-approve", help="Reject every gated action instead of prompting."
    ),
    dry_run: bool = typer.Option(
        False, "--dry-run", help="Plan and print the task graph without executing."
    ),
    json_out: bool = typer.Option(False, "--json", help="Print the run summary as JSON."),
) -> None:
    """Plan, execute and verify a goal."""
    config = _load_config(config_path)
    if planner:
        config.planner = planner  # type: ignore[assignment]
    if plan_file:
        config.planner = "static"
        config.plan_file = str(plan_file)
    if provider:
        config.model.provider = provider
    if model:
        config.model.name = model
    if yes and no_approve:
        _fail("--yes and --no-approve are mutually exclusive")

    gate = AutoApproveGate() if yes else DenyAllGate() if no_approve else ConsoleGate()
    if yes:
        config.security.approval_gate = "auto"

    try:
        engine = build_engine(config, approval_gate=gate)
    except (ConfigError, KeyError) as exc:
        _fail(str(exc), code=2)
        raise  # pragma: no cover

    goal_obj = make_goal(goal, list(constraint), list(criterion))

    if dry_run:
        try:
            plan = engine.planner.plan(goal_obj, engine.tools)
        except PlanningError as exc:
            _fail(str(exc), code=4)
            raise  # pragma: no cover
        console.print(Panel(goal_obj.description, title="Goal", border_style="cyan"))
        table = Table("task", "tool", "depends on", "verification", box=None)
        for task in plan.tasks:
            table.add_row(
                task.task_id,
                task.tool,
                ", ".join(task.depends_on) or "-",
                ", ".join(v.verifier for v in task.verification) or "[red]none[/]",
            )
        console.print(table)
        console.print(f"\n[dim]{len(plan.tasks)} task(s); nothing was executed.[/]")
        raise typer.Exit(0)

    # With --json the ONLY thing on stdout is the JSON document, so the command
    # can be piped into jq or consumed by CI without post-processing.
    if json_out:
        result = engine.run(goal_obj)
        typer.echo(json.dumps(summarise(result.run, result.events.events), indent=2))
    else:
        console.print(Panel(goal_obj.description, title="Goal", border_style="cyan"))
        with console.status("[cyan]executing…", spinner="dots"):
            result = engine.run(goal_obj)
        _print_result(result)
    raise typer.Exit(0 if result.ok else 1)


def _print_result(result: RunResult) -> None:
    run_obj = result.run
    table = Table(title=f"Run {run_obj.run_id}", box=None)
    table.add_column("task")
    table.add_column("status")
    table.add_column("attempts", justify="right")
    table.add_column("evidence")
    for task in result.tasks:
        checks = sum(v.checks for a in task.attempts for v in a.verifications)
        failures = [f for a in task.attempts for v in a.verifications for f in v.failures]
        style = _TASK_STYLE.get(task.status, "white")
        table.add_row(
            task.task_id,
            f"[{style}]{task.status.value}[/]",
            str(task.attempt_count),
            failures[-1][:60] if task.status is TaskStatus.FAILED and failures
            else f"{checks} check(s) passed",
        )
    console.print(table)

    if run_obj.artifacts:
        console.print("\n[bold]Artifacts[/]")
        for artifact in run_obj.artifacts:
            console.print(
                f"  {artifact.path} [dim]({artifact.bytes} B, "
                f"sha256 {artifact.sha256[:12]}…)[/]"
            )

    stats = summarise(run_obj, result.events.events)
    ok = run_obj.status is RunStatus.COMPLETED
    console.print(
        Panel(
            f"{stats['tasks_completed']}/{stats['tasks_total']} tasks completed  ·  "
            f"{stats['verification_checks']} verification checks  ·  "
            f"{stats['tool_calls']} tool calls  ·  {stats['artifacts']} artifacts\n"
            f"report: {result.report_path}\n"
            f"inspect: astraforge inspect {run_obj.run_id}",
            title=f"[{'green' if ok else 'red'}]{run_obj.status.value}[/]",
            border_style="green" if ok else "red",
        )
    )


# --------------------------------------------------------------------------- #
# inspection
# --------------------------------------------------------------------------- #


@app.command("runs")
def list_runs(
    config_path: Path | None = typer.Option(None, "--config", "-c"),
    limit: int = typer.Option(20, "--limit", "-n"),
) -> None:
    """List recorded runs, newest first."""
    store = _store(_load_config(config_path))
    ids = store.list_runs()[:limit]
    if not ids:
        console.print("[yellow]no runs recorded yet[/]")
        raise typer.Exit(0)
    table = Table("run id", "status", "tasks", "started", "goal", box=None)
    for run_id in ids:
        record = store.load_run(run_id)
        tasks = record.plan.tasks if record.plan else []
        done = sum(1 for t in tasks if t.status is TaskStatus.COMPLETED)
        style = "green" if record.status is RunStatus.COMPLETED else "red"
        table.add_row(
            run_id,
            f"[{style}]{record.status.value}[/]",
            f"{done}/{len(tasks)}",
            record.started_at.strftime("%Y-%m-%d %H:%M"),
            record.goal.description[:50],
        )
    console.print(table)


@app.command()
def inspect(
    run_id: str = typer.Argument("latest", help="Run id, id prefix, or 'latest'."),
    config_path: Path | None = typer.Option(None, "--config", "-c"),
    json_out: bool = typer.Option(False, "--json", help="Print the raw run record."),
) -> None:
    """Show the plan, task outcomes and verification evidence for a run."""
    store = _store(_load_config(config_path))
    record = store.load_run(_resolve(store, run_id))
    if json_out:
        console.print_json(record.model_dump_json())
        raise typer.Exit(0)

    report = store.report_path(record.run_id)
    if report.exists():
        console.print(
            Syntax(report.read_text(encoding="utf-8"), "markdown", word_wrap=True)
        )
    else:  # pragma: no cover - only if the report was deleted
        console.print(record.model_dump_json(indent=2))


@app.command()
def logs(
    run_id: str = typer.Argument("latest"),
    config_path: Path | None = typer.Option(None, "--config", "-c"),
    json_out: bool = typer.Option(False, "--json", help="Emit raw JSONL."),
    event_type: str | None = typer.Option(
        None, "--type", "-t", help="Filter by event type prefix, e.g. 'task'."
    ),
) -> None:
    """Print the structured event log for a run."""
    store = _store(_load_config(config_path))
    resolved = _resolve(store, run_id)
    events = store.load_events(resolved)
    if event_type:
        events = [e for e in events if e.type.value.startswith(event_type)]
    if not events:
        console.print("[yellow]no matching events[/]")
        raise typer.Exit(0)
    for event in events:
        if json_out:
            typer.echo(event.model_dump_json())
        else:
            console.print(
                f"[dim]{event.timestamp.strftime('%H:%M:%S')}[/] "
                f"[cyan]{event.type.value:<22}[/] "
                f"[dim]{event.actor:<18}[/] {event.message}"
            )


@app.command()
def artifacts(
    run_id: str = typer.Argument("latest"),
    config_path: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """List the artifacts a run produced, with sizes and hashes."""
    store = _store(_load_config(config_path))
    resolved = _resolve(store, run_id)
    record = store.load_run(resolved)
    if not record.artifacts:
        console.print("[yellow]this run produced no artifacts[/]")
        raise typer.Exit(0)
    table = Table("path", "kind", "bytes", "sha256", "task", box=None)
    for artifact in record.artifacts:
        table.add_row(
            artifact.path,
            artifact.kind,
            str(artifact.bytes),
            artifact.sha256[:16] + "…",
            artifact.produced_by,
        )
    console.print(table)
    console.print(f"\n[dim]workspace: {store.workspace_dir(resolved)}[/]")


@app.command()
def verify(
    run_id: str = typer.Argument("latest"),
    config_path: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Re-check a finished run: are its artifacts and its history still intact?"""
    store = _store(_load_config(config_path))
    resolved = _resolve(store, run_id)
    record = store.load_run(resolved)
    workspace = Workspace(store.workspace_dir(resolved))

    # The execution log is evidence too. Verifying artifacts while ignoring the
    # record of how they were produced would leave the more interesting target
    # unprotected: rewriting history is how you hide a failure.
    sink = JsonlEventSink(store.events_path(resolved))
    chain = sink.verify()
    # A chain prefix is internally consistent, so a hash chain alone cannot
    # detect events dropped from the end. The run record pins the expected count.
    truncated = (
        record.event_count > 0 and chain.checked < record.event_count
    )

    # A path may have several artifact revisions if successive tasks rewrote
    # it. Only the final revision should still be on disk; earlier ones were
    # legitimately superseded, so they are reported, not flagged as tampering.
    final: dict[str, Artifact] = {}
    for artifact in record.artifacts:
        final[artifact.path] = artifact
    superseded = len(record.artifacts) - len(final)

    problems: list[str] = []
    for artifact in final.values():
        path = workspace.resolve(artifact.path)
        if not path.is_file():
            problems.append(f"missing artifact: {artifact.path}")
            continue
        actual = workspace.sha256(path)
        if actual != artifact.sha256:
            problems.append(
                f"hash mismatch for {artifact.path}: "
                f"recorded {artifact.sha256[:12]}…, on disk {actual[:12]}…"
            )
        else:
            console.print(f"[green]ok[/] {artifact.path}")
    if superseded:
        console.print(
            f"[dim]{superseded} earlier artifact revision(s) superseded during the run[/]"
        )

    unverified = [
        t.task_id
        for t in (record.plan.tasks if record.plan else [])
        if not t.verification
    ]
    if unverified:
        console.print(
            f"[yellow]warning[/] task(s) with no verification: {', '.join(unverified)}"
        )
    if chain.intact:
        console.print(f"[green]ok[/] event log: {chain.summary}")
    else:
        unverifiable_only = all(
            "written before chaining" in b.problem for b in chain.breaks
        )
        if unverifiable_only:
            # An upgraded install reading an old run is not evidence of tampering.
            console.print(
                "[yellow]warning[/] event log predates integrity chaining "
                "and cannot be verified"
            )
        else:
            for brk in chain.breaks[:5]:
                problems.append(f"event log: {brk}")

    if truncated:
        problems.append(
            f"event log truncated: {chain.checked} events on disk, "
            f"{record.event_count} recorded for this run"
        )

    if problems:
        for problem in problems:
            console.print(f"[red]fail[/] {problem}")
        raise typer.Exit(1)
    console.print(
        f"\n[green]{len(final)} artifact(s) match their recorded hashes[/]"
    )


@app.command()
def tools(
    config_path: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """List available tools and verifiers with their permissions."""
    from astraforge.core.factory import build_provider

    config = _load_config(config_path)
    registry = default_registry(build_provider(config))
    table = Table("tool", "risk", "reversible", "capabilities", "description", box=None)
    for tool in sorted(registry, key=lambda t: t.name):
        table.add_row(
            tool.name,
            tool.risk.value,
            "yes" if tool.reversible else "[red]no[/]",
            ", ".join(sorted(c.value for c in tool.capabilities)),
            tool.description[:60],
        )
    console.print(table)
    console.print(f"\n[bold]verifiers:[/] {', '.join(default_verifiers().names())}")
    granted = sorted(c.value for c in config.security.policy().granted)
    console.print(f"[bold]granted capabilities:[/] {', '.join(granted)}")
    console.print(
        f"[bold]approval required at/above risk:[/] "
        f"{config.security.approval_at_or_above.value}"
    )
    # State plainly what this machine can enforce. A user must never assume a
    # sandbox that is not actually active.
    support = probe_support()
    colour = "green" if support.network_namespaces else "yellow"
    console.print(f"[bold]process isolation:[/] [{colour}]{describe_isolation()}[/]")


@app.command()
def cancel(
    run_id: str = typer.Argument(...),
    config_path: Path | None = typer.Option(None, "--config", "-c"),
) -> None:
    """Mark an unfinished run as cancelled."""
    store = _store(_load_config(config_path))
    resolved = _resolve(store, run_id)
    record = store.load_run(resolved)
    if record.status in {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}:
        _fail(f"run {resolved} already finished with status {record.status.value}")
    record.status = RunStatus.CANCELLED
    record.notes.append("cancelled by operator")
    store.save_run(record)
    console.print(f"[yellow]cancelled[/] {resolved}")


def main() -> None:  # pragma: no cover - console entry point
    try:
        app()
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted[/]")
        sys.exit(130)


if __name__ == "__main__":  # pragma: no cover
    main()
