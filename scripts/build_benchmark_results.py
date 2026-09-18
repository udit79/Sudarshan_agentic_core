"""Build traceable benchmark exports and Matplotlib charts.

This is reporting-only. It reads a checked-in, sanitized JSON dataset and
does not call providers, databases, Cognee, or the application API.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import tempfile
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Keep Matplotlib's font cache in a writable temporary location. This avoids
# touching a user's profile and keeps report generation independent of the
# Windows account that runs the repository.
os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "sudarshan-matplotlib-cache"))

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


DEFAULT_INPUT = ROOT / "docs" / "all test phases" / "benchmark-results" / "benchmark-results.json"
DEFAULT_OUTPUT = DEFAULT_INPUT.parent


def _records(data: dict[str, Any]) -> list[dict[str, Any]]:
    records = data.get("records")
    if not isinstance(records, list) or not all(isinstance(item, dict) for item in records):
        raise ValueError("benchmark dataset must contain a list of record objects")
    return records


def _save(fig: Any, output: Path, record_ids: list[str], columns: list[str], manifest: list[dict[str, Any]]) -> None:
    fig.tight_layout()
    fig.savefig(output, dpi=160, bbox_inches="tight")
    plt.close(fig)
    manifest.append({"file": output.name, "record_ids": record_ids, "data_columns": columns})


def _suite_rows(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [record for record in records if record.get("record_type") == "test_suite"]


def build_outputs(input_path: Path = DEFAULT_INPUT, output_dir: Path = DEFAULT_OUTPUT) -> list[Path]:
    data = json.loads(input_path.read_text(encoding="utf-8"))
    records = _records(data)
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest: list[dict[str, Any]] = []
    generated: list[Path] = []

    csv_path = output_dir / "benchmark-results.csv"
    fields = [
        "record_id", "record_type", "case_id", "pipeline", "run_id", "outcome",
        "quality_status", "source_kind", "source", "duration_ms", "total_tests",
        "passed_tests", "failed_tests", "skipped_tests", "failure_rate",
        "correctness", "truthfulness_factual_grounding", "evidence_adherence",
        "constraint_adherence", "completeness", "artifact_quality", "tokens_input",
        "tokens_output", "tokens_reasoning", "tokens_total", "cost_usd",
        "human_evaluation_status", "human_evaluation_score"
    ]
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for record in records:
            counts = record.get("test_counts", {})
            metrics = record.get("objective_metrics", {})
            tokens = metrics.get("token_usage") or {}
            human = record.get("human_evaluation", {})
            writer.writerow({
                "record_id": record.get("record_id"),
                "record_type": record.get("record_type"),
                "case_id": record.get("case_id"),
                "pipeline": record.get("pipeline"),
                "run_id": record.get("run_id"),
                "outcome": record.get("outcome"),
                "quality_status": record.get("quality_status"),
                "source_kind": record.get("source_kind"),
                "source": record.get("source"),
                "duration_ms": record.get("duration_ms"),
                "total_tests": counts.get("total"),
                "passed_tests": counts.get("passed"),
                "failed_tests": counts.get("failed"),
                "skipped_tests": counts.get("skipped"),
                "failure_rate": metrics.get("failure_rate"),
                "correctness": metrics.get("correctness"),
                "truthfulness_factual_grounding": metrics.get("truthfulness_factual_grounding"),
                "evidence_adherence": metrics.get("evidence_adherence"),
                "constraint_adherence": metrics.get("constraint_adherence"),
                "completeness": metrics.get("completeness"),
                "artifact_quality": metrics.get("artifact_quality"),
                "tokens_input": tokens.get("input"),
                "tokens_output": tokens.get("output"),
                "tokens_reasoning": tokens.get("reasoning"),
                "tokens_total": tokens.get("total"),
                "cost_usd": metrics.get("cost_usd"),
                "human_evaluation_status": human.get("status"),
                "human_evaluation_score": human.get("score"),
            })
    generated.append(csv_path)

    suites = _suite_rows(records)
    labels = [record["record_id"].replace("suite-", "").replace("-20260918", "").replace("-20260917", "") for record in suites]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    x = list(range(len(suites)))
    passed = [record["test_counts"].get("passed") or 0 for record in suites]
    failed = [record["test_counts"].get("failed") or 0 for record in suites]
    skipped = [record["test_counts"].get("skipped") or 0 for record in suites]
    ax.bar(x, passed, label="passed", color="#2e8b57")
    ax.bar(x, failed, bottom=passed, label="failed", color="#c0392b")
    ax.bar(x, skipped, bottom=[p + f for p, f in zip(passed, failed)], label="skipped", color="#d4ac0d")
    ax.set_title("Objective automated test outcomes")
    ax.set_ylabel("test count")
    ax.set_xticks(x, labels, rotation=25, ha="right")
    ax.legend()
    path = output_dir / "objective-test-outcomes.png"
    _save(fig, path, [record["record_id"] for record in suites], ["test_counts.passed", "test_counts.failed", "test_counts.skipped"], manifest)
    generated.append(path)

    fig, ax = plt.subplots(figsize=(11, 5.5))
    durations = [record["duration_ms"] / 1000 for record in suites if record.get("duration_ms") is not None]
    duration_records = [record for record in suites if record.get("duration_ms") is not None]
    ax.bar(range(len(duration_records)), durations, color="#2874a6")
    ax.set_title("Offline test-suite execution time")
    ax.set_ylabel("seconds")
    ax.set_xticks(range(len(duration_records)), [record["record_id"].replace("suite-", "") for record in duration_records], rotation=25, ha="right")
    path = output_dir / "offline-test-suite-duration.png"
    _save(fig, path, [record["record_id"] for record in duration_records], ["duration_ms"], manifest)
    generated.append(path)

    live = next(record for record in records if record["record_id"] == "case-g01-live-usage-20260918")
    live_metrics = live["objective_metrics"]
    tokens = live_metrics["token_usage"]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.bar(["input", "output", "reasoning"], [tokens["input"], tokens["output"], tokens["reasoning"]], color=["#5dade2", "#58d68d", "#af7ac5"])
    ax.set_title("G01 live provider-reported tokens")
    ax.set_ylabel("tokens")
    path = output_dir / "live-g01-token-usage.png"
    _save(fig, path, [live["record_id"]], ["objective_metrics.token_usage.input", "objective_metrics.token_usage.output", "objective_metrics.token_usage.reasoning"], manifest)
    generated.append(path)

    op = live["operational_measurements"]
    fig, ax = plt.subplots(figsize=(8, 5))
    labels = ["admission", "memory recall 1", "memory recall 2", "Crew wall"]
    values = [op["admission_ms"], op["memory_recall_ms_first"], op["memory_recall_ms_second"], live["duration_ms"]]
    ax.bar(labels, values, color="#e67e22")
    ax.set_title("G01 live timing observations")
    ax.set_ylabel("milliseconds")
    ax.set_yscale("log")
    ax.tick_params(axis="x", rotation=20)
    path = output_dir / "live-g01-timing.png"
    _save(fig, path, [live["record_id"]], ["operational_measurements.admission_ms", "operational_measurements.memory_recall_ms_first", "operational_measurements.memory_recall_ms_second", "duration_ms"], manifest)
    generated.append(path)

    harness = next(record for record in records if record["record_id"] == "benchmark-harness-boundary-20260918")
    hop = harness["operational_measurements"]
    fig, ax = plt.subplots(figsize=(7, 5))
    ax.bar(["full MCP tools", "artifact profile tools", "renderers"], [hop["full_mcp_tools"], hop["artifact_profile_tools"], hop["renderer_count"]], color="#7d3c98")
    ax.set_title("Offline harness capability counts")
    ax.set_ylabel("count")
    path = output_dir / "offline-harness-capabilities.png"
    _save(fig, path, [harness["record_id"]], ["operational_measurements.full_mcp_tools", "operational_measurements.artifact_profile_tools", "operational_measurements.renderer_count"], manifest)
    generated.append(path)

    manifest_path = output_dir / "chart-manifest.json"
    manifest_path.write_text(json.dumps({"dataset": input_path.name, "charts": manifest}, indent=2) + "\n", encoding="utf-8")
    generated.append(manifest_path)
    return generated


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    paths = build_outputs(args.input, args.output_dir)
    print(f"generated {len(paths)} benchmark outputs in {args.output_dir}")
    for path in paths:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
