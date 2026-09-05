"""Proof-of-work report.

Answers one question: *why should anyone believe the agent did the job?*
Everything in the report is derived from recorded events, task attempts and
content-hashed artifacts — nothing is asserted by a model.
"""

from __future__ import annotations

from collections import Counter

from astraforge.models.core import Run, TaskStatus
from astraforge.models.events import Event, EventType


def summarise(run: Run, events: list[Event]) -> dict[str, object]:
    """Machine-readable run statistics, used by the report and the CLI."""
    tasks = run.plan.tasks if run.plan else []
    counts = Counter(e.type for e in events)
    completed = [t for t in tasks if t.status is TaskStatus.COMPLETED]
    recovered = [t for t in completed if t.attempt_count > 1]
    checks = sum(
        v.checks for t in tasks for a in t.attempts for v in a.verifications
    )
    return {
        "run_id": run.run_id,
        "status": run.status.value,
        "goal": run.goal.description,
        "provider": run.provider,
        "tasks_total": len(tasks),
        "tasks_completed": len(completed),
        "tasks_failed": sum(1 for t in tasks if t.status is TaskStatus.FAILED),
        "tasks_blocked": sum(1 for t in tasks if t.status is TaskStatus.BLOCKED),
        "tool_calls": counts[EventType.TOOL_CALLED],
        "tool_failures": counts[EventType.TOOL_FAILED],
        "verification_checks": checks,
        "verifications_failed": counts[EventType.VERIFICATION_FAILED],
        "initial_failures": counts[EventType.TOOL_FAILED]
        + counts[EventType.VERIFICATION_FAILED],
        "recovered_failures": len(recovered),
        "policy_blocks": counts[EventType.POLICY_BLOCKED],
        "human_interventions": counts[EventType.APPROVAL_GRANTED]
        + counts[EventType.APPROVAL_DENIED],
        "artifacts": len(run.artifacts),
        "duration_s": run.duration_s,
        "events": len(events),
    }


_STATUS_MARK = {
    TaskStatus.COMPLETED: "PASS",
    TaskStatus.FAILED: "FAIL",
    TaskStatus.BLOCKED: "BLOCKED",
    TaskStatus.CANCELLED: "CANCELLED",
}


def build_report(run: Run, events: list[Event]) -> str:
    """Render the Markdown execution report for a finished run."""
    stats = summarise(run, events)
    lines: list[str] = [
        "# AstraForge run report",
        "",
        f"- **Run id:** `{run.run_id}`",
        f"- **Status:** {run.status.value}",
        f"- **Goal:** {run.goal.description}",
        f"- **Provider:** {run.provider or 'none'}",
        f"- **Started:** {run.started_at.isoformat()}",
        f"- **Duration:** {run.duration_s}s",
        "",
        "## Summary",
        "",
        "| Metric | Value |",
        "| --- | --- |",
        f"| Tasks completed | {stats['tasks_completed']}/{stats['tasks_total']} |",
        f"| Tasks failed | {stats['tasks_failed']} |",
        f"| Tasks blocked | {stats['tasks_blocked']} |",
        f"| Tool calls | {stats['tool_calls']} |",
        f"| Tool failures | {stats['tool_failures']} |",
        f"| Verification checks | {stats['verification_checks']} |",
        f"| Verification failures | {stats['verifications_failed']} |",
        f"| Failures recovered by retry | {stats['recovered_failures']} |",
        f"| Policy blocks | {stats['policy_blocks']} |",
        f"| Human interventions | {stats['human_interventions']} |",
        f"| Artifacts | {stats['artifacts']} |",
        f"| Events recorded | {stats['events']} |",
        "",
    ]

    if run.goal.constraints or run.goal.success_criteria:
        lines.append("## Goal detail")
        lines.append("")
        for label, values in (
            ("Constraints", run.goal.constraints),
            ("Success criteria", run.goal.success_criteria),
        ):
            if values:
                lines.append(f"**{label}**")
                lines.append("")
                lines += [f"- {v}" for v in values]
                lines.append("")

    if run.plan:
        lines += ["## Plan", ""]
        if run.plan.assumptions:
            lines.append("**Assumptions**")
            lines.append("")
            lines += [f"- {a}" for a in run.plan.assumptions]
            lines.append("")
        if run.plan.objectives:
            lines.append("**Objectives**")
            lines.append("")
            lines += [f"- {o}" for o in run.plan.objectives]
            lines.append("")

        lines += ["## Tasks", ""]
        for task in run.plan.tasks:
            mark = _STATUS_MARK.get(task.status, task.status.value)
            lines.append(f"### `{task.task_id}` — {mark}")
            lines.append("")
            lines.append(f"{task.description}")
            lines.append("")
            lines.append(f"- Tool: `{task.tool}` (risk {task.risk.value})")
            if task.depends_on:
                lines.append(f"- Depends on: {', '.join(f'`{d}`' for d in task.depends_on)}")
            lines.append(f"- Attempts: {task.attempt_count}")
            lines.append("")
            for attempt in task.attempts:
                verdict = "ok" if attempt.ok else (attempt.error or "failed")
                lines.append(f"**Attempt {attempt.attempt}** — {verdict}")
                lines.append("")
                if attempt.failure_class:
                    lines.append(
                        f"- Failure class: `{attempt.failure_class.value}` "
                        f"(recoverable: {attempt.failure_class.recoverable})"
                    )
                if attempt.tool_call:
                    call = attempt.tool_call
                    lines.append(
                        f"- Tool `{call.tool}` -> "
                        f"{'ok' if call.ok else 'failed'} in {call.duration_ms}ms"
                    )
                    lines += [f"  - {e.summary}" for e in call.evidence]
                for verification in attempt.verifications:
                    lines.append(
                        f"- Verifier `{verification.verifier}`: "
                        f"{verification.status.value} "
                        f"({verification.checks} check(s))"
                    )
                    lines += [f"  - evidence: {e.summary}" for e in verification.evidence]
                    lines += [f"  - FAILURE: {f}" for f in verification.failures]
                lines.append("")

    lines += ["## Artifacts", ""]
    if run.artifacts:
        lines.append("| Path | Kind | Bytes | SHA-256 | Produced by |")
        lines.append("| --- | --- | --- | --- | --- |")
        for artifact in run.artifacts:
            lines.append(
                f"| `{artifact.path}` | {artifact.kind} | {artifact.bytes} "
                f"| `{artifact.sha256[:16]}…` | `{artifact.produced_by}` |"
            )
    else:
        lines.append("_No artifacts were produced._")
    lines.append("")

    if run.notes:
        lines += ["## Notes", ""] + [f"- {n}" for n in run.notes] + [""]

    lines += [
        "## Reproducing this run",
        "",
        "```bash",
        f"astraforge inspect {run.run_id}   # plan, tasks, verification",
        f"astraforge logs {run.run_id}      # full structured event log",
        f"astraforge artifacts {run.run_id} # artifact inventory with hashes",
        f"astraforge verify {run.run_id}    # re-check artifact hashes",
        "```",
        "",
        "Every claim above is derived from the recorded event log and from "
        "content hashes of files on disk, not from model output.",
        "",
    ]
    return "\n".join(lines)
