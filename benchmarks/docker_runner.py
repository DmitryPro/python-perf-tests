"""Utilities for building and executing all benchmark Docker images.

In addition to orchestrating ``docker build`` / ``docker run`` cycles this
module can persist benchmark outputs to a shared directory and produce a simple
aggregated summary across Python versions.
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKER_ROOT = REPO_ROOT / "docker"


def _default_results_dir_for_suite(suite: str) -> Path:
    base = REPO_ROOT / "results"
    if suite == "micro":
        return base / "micro"
    if suite == "concurrency":
        return base / "concurrency"
    raise DockerRunnerError(f"Unsupported benchmark suite '{suite}'")



def _baseline_mean(results: Sequence[dict]) -> float | None:
    """Return the CPython 3.14 baseline mean, preferring GIL-enabled builds."""

    def _matches(entry: dict) -> bool:
        implementation = entry.get("python_implementation")
        version = entry.get("python_version", "")
        mean = entry.get("mean")
        return (
            implementation == "CPython"
            and isinstance(version, str)
            and version.startswith("3.14")
            and isinstance(mean, (int, float))
        )

    def _is_thread_free(version: str) -> bool:
        return version.lower().endswith("t")

    candidates = [entry for entry in results if _matches(entry)]
    for entry in candidates:
        version = entry.get("python_version", "")
        if isinstance(version, str) and not _is_thread_free(version):
            return float(entry["mean"])

    if candidates:
        return float(candidates[0]["mean"])
    return None


def _format_relative(relative: float | None) -> str:
    if relative is None:
        return ""
    if math.isclose(relative, 1.0, rel_tol=0.02):
        return " [on par with CPython 3.14]"
    if relative < 1.0:
        faster = 1 / relative
        return f" [{faster:.2f}x faster vs CPython 3.14]"
    slower = relative
    return f" [{slower:.2f}x slower vs CPython 3.14]"


class DockerRunnerError(RuntimeError):
    """Raised when the Docker layout is invalid."""


@dataclass(frozen=True)
class DockerTarget:
    """Represents a single Docker build/run target."""

    version: str
    dockerfile: Path

    @property
    def tag(self) -> str:
        return f"python-perf:{self.version}"


def discover_targets(docker_root: Path = DOCKER_ROOT) -> List[DockerTarget]:
    """Discover Docker build targets under ``docker_root``.

    Parameters
    ----------
    docker_root:
        Path containing sub-directories for each Python version.

    Returns
    -------
    list[DockerTarget]
        Targets sorted by version string.
    """

    if not docker_root.exists():
        raise DockerRunnerError(f"Docker root '{docker_root}' does not exist")

    targets: List[DockerTarget] = []
    for entry in sorted(docker_root.iterdir()):
        if not entry.is_dir():
            continue
        name = entry.name
        if not name.startswith("py"):
            raise DockerRunnerError(
                f"Unexpected docker directory name '{name}' (expected prefix 'py')"
            )
        version = name[2:]
        dockerfile = entry / "Dockerfile"
        if not dockerfile.exists():
            raise DockerRunnerError(f"Missing Dockerfile for version {version}: {dockerfile}")
        targets.append(DockerTarget(version=version, dockerfile=dockerfile))
    return targets


def run_command(command: Sequence[str], dry_run: bool = False) -> None:
    """Execute ``command`` with optional dry-run logging."""

    print("$", " ".join(shlex.quote(part) for part in command))
    if dry_run:
        return
    subprocess.run(command, check=True)


def build_image(target: DockerTarget, *, context: Path, dry_run: bool) -> None:
    run_command(
        [
            "docker",
            "build",
            "-f",
            str(target.dockerfile),
            "-t",
            target.tag,
            str(context),
        ],
        dry_run=dry_run,
    )


def run_container(
    target: DockerTarget,
    *,
    dry_run: bool,
    run_cmd: Sequence[str] | None,
    results_dir: Path | None,
) -> None:
    command: List[str] = ["docker", "run", "--rm"]
    if results_dir is not None:
        command.extend(["-v", f"{results_dir.resolve()}:/app/results"])
    command.append(target.tag)
    if run_cmd:
        command.extend(run_cmd)
    run_command(command, dry_run=dry_run)


def execute(
    *,
    context: Path = REPO_ROOT,
    docker_root: Path = DOCKER_ROOT,
    skip_build: bool = False,
    skip_run: bool = False,
    dry_run: bool = False,
    run_cmd: Sequence[str] | None = None,
    results_dir: Path | None = None,
    aggregate: bool = True,
    iterations: int | None = None,
    repeat: int | None = None,
    suite: str = "micro",
    tasks: int | None = None,
    workers: int | None = None,
) -> List[DockerTarget]:
    """Build and run all Docker images.

    Returns the ordered list of processed :class:`DockerTarget` objects.
    """

    targets = discover_targets(docker_root)

    if results_dir is not None:
        if dry_run or skip_run:
            results_dir.mkdir(parents=True, exist_ok=True)
        else:
            _reset_results_dir(results_dir)

    if run_cmd is not None:
        command_builder = lambda target: [list(run_cmd)]
    elif suite == "concurrency":
        command_builder = lambda target: _build_concurrency_commands(
            tasks, workers, target.version
        )
    elif suite == "micro":
        base_command = _build_benchmark_command(iterations, repeat)

        def command_builder(target: DockerTarget) -> List[List[str]]:
            return [list(base_command)]

    else:
        raise DockerRunnerError(f"Unsupported benchmark suite '{suite}'")

    for target in targets:
        if not skip_build:
            build_image(target, context=context, dry_run=dry_run)
        if not skip_run:
            for command in command_builder(target):
                run_container(
                    target,
                    dry_run=dry_run,
                    run_cmd=command,
                    results_dir=results_dir,
                )

    if (
        not skip_run
        and not dry_run
        and aggregate
        and results_dir is not None
    ):
        summary_text = summarize_results(results_dir, suite=suite)
        if summary_text:
            print(summary_text)
    return targets


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--suite",
        choices=("micro", "concurrency"),
        default="micro",
        help="Benchmark suite to execute inside each container",
    )
    parser.add_argument(
        "--docker-root",
        type=Path,
        default=DOCKER_ROOT,
        help="Directory that contains per-version Dockerfiles",
    )
    parser.add_argument(
        "--context",
        type=Path,
        default=REPO_ROOT,
        help="Docker build context (defaults to repository root)",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Do not build images; only run them",
    )
    parser.add_argument(
        "--skip-run",
        action="store_true",
        help="Build images but do not run containers",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print docker commands without executing them",
    )
    parser.add_argument(
        "--run-cmd",
        type=str,
        default=None,
        help=(
            "Override the command executed inside each container. "
            "Provide a shell-style string that will be tokenized with shlex."
        ),
    )
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=None,
        help=(
            "Directory on the host where benchmark results are stored. "
            "Defaults to a suite-specific directory under 'results/'."
        ),
    )
    parser.add_argument(
        "--no-aggregate",
        action="store_true",
        help="Do not aggregate collected benchmark JSON files",
    )
    parser.add_argument(
        "--iterations",
        type=int,
        default=None,
        help="Override iterations passed to benchmarks inside containers",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=None,
        help="Override repeats passed to benchmarks inside containers",
    )
    parser.add_argument(
        "--tasks",
        type=int,
        default=None,
        help="Override concurrency benchmark tasks per workload",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=None,
        help="Override concurrency benchmark worker count",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_cmd = shlex.split(args.run_cmd) if args.run_cmd else None

    parameter_overrides = (
        args.iterations,
        args.repeat,
        args.tasks,
        args.workers,
    )

    if run_cmd is not None and any(value is not None for value in parameter_overrides):
        print(
            "Error: --run-cmd cannot be combined with benchmark parameter overrides"
        )
        return 1

    if args.suite == "micro" and (
        args.tasks is not None or args.workers is not None
    ):
        print("Error: --tasks/--workers overrides require --suite concurrency")
        return 1

    if args.suite == "concurrency" and (
        args.iterations is not None or args.repeat is not None
    ):
        print("Error: --iterations/--repeat overrides are unavailable for the concurrency suite")
        return 1

    try:
        results_dir = (
            args.results_dir
            if args.results_dir is not None
            else _default_results_dir_for_suite(args.suite)
        )
        execute(
            context=args.context,
            docker_root=args.docker_root,
            skip_build=args.skip_build,
            skip_run=args.skip_run,
            dry_run=args.dry_run,
            run_cmd=run_cmd,
            results_dir=results_dir,
            aggregate=not args.no_aggregate,
            iterations=args.iterations,
            repeat=args.repeat,
            suite=args.suite,
            tasks=args.tasks,
            workers=args.workers,
        )
    except (DockerRunnerError, subprocess.CalledProcessError) as exc:
        print(f"Error: {exc}")
        return 1
    return 0


def _build_benchmark_command(
    iterations: int | None, repeat: int | None
) -> List[str]:
    command: List[str] = ["python", "-m", "benchmarks.benchmark"]
    if iterations is not None:
        command.extend(["--iterations", str(iterations)])
    if repeat is not None:
        command.extend(["--repeat", str(repeat)])
    return command


def _build_concurrency_commands(
    tasks: int | None, workers: int | None, python_version: str
) -> List[List[str]]:
    options: List[str] = []
    if tasks is not None:
        options.extend(["--tasks", str(tasks)])
    if workers is not None:
        options.extend(["--workers", str(workers)])

    commands = []

    if python_version.startswith("3.14"):
        if "ft" in python_version:
            commands.append(
                [
                    "python3.14t",
                    "-m",
                    "benchmarks.concurrency",
                    *options,
                ]
            )
        else:
            commands.append(
                [
                    "python",
                    "-m",
                    "benchmarks.concurrency",
                    *options,
                ]
            )

    return commands


def summarize_results(results_dir: Path, *, suite: str = "micro") -> str | None:
    """Aggregate benchmark JSON files for ``suite`` and return a summary string."""

    if suite == "micro":
        return _summarize_micro_results(results_dir)
    if suite == "concurrency":
        return _summarize_concurrency_results(results_dir)
    raise DockerRunnerError(f"Unsupported benchmark suite '{suite}'")


def _summarize_micro_results(results_dir: Path) -> str | None:
    payloads = list(_load_micro_payloads(results_dir))
    if not payloads:
        return None

    sorted_payloads = sorted(
        payloads,
        key=lambda payload: (
            payload.get("python_implementation", ""),
            _version_sort_key(payload.get("python_version", "")),
        ),
    )
    summary = _aggregate_micro_payloads(sorted_payloads)
    (results_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return _format_micro_summary(summary)


def _summarize_concurrency_results(results_dir: Path) -> str | None:
    payloads = list(_load_concurrency_payloads(results_dir))
    if not payloads:
        return None

    sorted_payloads = sorted(payloads, key=_runtime_metadata_sort_key)
    summary = _aggregate_concurrency_payloads(sorted_payloads)
    (results_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return _format_concurrency_summary(summary)


def _reset_results_dir(results_dir: Path) -> None:
    """Remove all files/sub-directories under ``results_dir`` and recreate it."""

    if results_dir.exists():
        for entry in results_dir.iterdir():
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()

    results_dir.mkdir(parents=True, exist_ok=True)


def _load_micro_payloads(results_dir: Path) -> Iterable[dict]:
    pattern = "benchmarks-*.json"
    for path in sorted(results_dir.glob(pattern)):
        try:
            yield json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"Warning: could not parse benchmark output '{path}'")


def _load_concurrency_payloads(results_dir: Path) -> Iterable[dict]:
    pattern = "concurrency-*.json"
    for path in sorted(results_dir.glob(pattern)):
        try:
            yield json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"Warning: could not parse concurrency output '{path}'")


def _version_key(version: str) -> Tuple[int, ...]:
    parts: List[int] = []
    for part in version.split("."):
        digits = ""
        for char in part:
            if char.isdigit():
                digits += char
            else:
                break
        if digits:
            parts.append(int(digits))
        else:
            break
        if len(digits) != len(part):
            break
    return tuple(parts)


def _version_sort_key(version: str) -> Tuple[Tuple[int, ...], int, str]:
    variant_rank = 1 if version.lower().endswith("t") else 0
    return (_version_key(version), variant_rank, version)


def _runtime_metadata_sort_key(payload: dict) -> Tuple[str, Tuple[Tuple[int, ...], int, str], int, str]:
    metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
    implementation = metadata.get("python_implementation", "")
    version = metadata.get("python_version", "")
    gil_rank = 1 if metadata.get("gil_disabled") is True else 0
    return (implementation, _version_sort_key(version), gil_rank, str(version))


def _aggregate_micro_payloads(payloads: Sequence[dict]) -> dict:
    case_order: List[str] = []
    seen_cases = set()
    for payload in payloads:
        for case in payload.get("cases", []):
            name = case.get("name")
            if name and name not in seen_cases:
                case_order.append(name)
                seen_cases.add(name)

    versions = [payload.get("python_version", "unknown") for payload in payloads]
    implementations = [
        payload.get("python_implementation", "unknown") for payload in payloads
    ]
    cases = []
    for case_name in case_order:
        results = []
        for payload in payloads:
            case_data = next(
                (
                    case
                    for case in payload.get("cases", [])
                    if case.get("name") == case_name
                ),
                None,
            )
            results.append(
                {
                    "python_implementation": payload.get(
                        "python_implementation", "unknown"
                    ),
                    "python_version": payload.get("python_version", "unknown"),
                    "iterations": payload.get("iterations"),
                    "repeat": payload.get("repeat"),
                    "mean": case_data.get("mean") if case_data else None,
                    "stdev": case_data.get("stdev") if case_data else None,
                }
            )

        baseline_mean = _baseline_mean(results)
        for entry in results:
            mean_value = entry.get("mean")
            if baseline_mean is not None and mean_value is not None and baseline_mean > 0:
                entry["relative_to_cpython_3_14"] = mean_value / baseline_mean
            else:
                entry["relative_to_cpython_3_14"] = None
        cases.append({"name": case_name, "results": results})

    runtimes = [
        {
            "python_implementation": impl,
            "python_version": version,
        }
        for impl, version in zip(implementations, versions)
    ]

    return {
        "suite": "micro",
        "python_versions": versions,
        "python_implementations": implementations,
        "python_runtimes": runtimes,
        "cases": cases,
    }


def _format_micro_summary(summary: dict) -> str:
    lines = ["Aggregate benchmark results (mean ± stdev seconds per run):"]
    for case in summary.get("cases", []):
        lines.append(f"- {case['name']}")
        for entry in case.get("results", []):
            implementation = entry.get("python_implementation", "unknown")
            version = entry.get("python_version", "unknown")
            mean = entry.get("mean")
            stdev = entry.get("stdev")
            iterations = entry.get("iterations")
            repeat = entry.get("repeat")
            relative = entry.get("relative_to_cpython_3_14")
            relative_text = _format_relative(relative)
            if mean is None:
                lines.append(f"    {implementation} {version}: no data")
            else:
                meta_parts = []
                if isinstance(iterations, int):
                    meta_parts.append(f"{iterations} iterations")
                if isinstance(repeat, int):
                    meta_parts.append(f"{repeat} repeats")
                meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
                lines.append(
                    f"    {implementation} {version}{meta}: {mean:.6f}s ± {stdev:.6f}s total{relative_text}"
                )
    if not summary.get("cases"):
        lines.append("(no benchmark cases found)")
    return "\n".join(lines)


def _aggregate_concurrency_payloads(payloads: Sequence[dict]) -> dict:
    workload_order: List[str] = []
    workload_metadata: Dict[str, Dict[str, object]] = {}
    for payload in payloads:
        for workload in payload.get("workloads", []):
            name = workload.get("name")
            if not name or name in workload_metadata:
                continue
            workload_order.append(name)
            workload_metadata[name] = {
                "category": workload.get("category"),
                "description": workload.get("description"),
            }

    runtime_details: List[Dict[str, object]] = []
    for payload in payloads:
        metadata = payload.get("metadata", {}) if isinstance(payload, dict) else {}
        implementation = metadata.get("python_implementation", "unknown")
        version = metadata.get("python_version", "unknown")
        runtime_entry: Dict[str, object] = {
            "python_implementation": implementation,
            "python_version": version,
        }
        for key in ("tasks", "workers", "gil_disabled"):
            value = metadata.get(key)
            if value is not None:
                runtime_entry[key] = value
        runtime_details.append(runtime_entry)

    workloads: List[Dict[str, object]] = []
    for workload_name in workload_order:
        metadata = workload_metadata.get(workload_name, {})
        workload_results: List[Dict[str, object]] = []
        for payload, runtime_info in zip(payloads, runtime_details):
            workload_payload = next(
                (
                    workload
                    for workload in payload.get("workloads", [])
                    if workload.get("name") == workload_name
                ),
                None,
            )
            entry: Dict[str, object] = {
                "python_implementation": runtime_info.get(
                    "python_implementation", "unknown"
                ),
                "python_version": runtime_info.get("python_version", "unknown"),
            }
            for key in ("tasks", "workers", "gil_disabled"):
                if key in runtime_info:
                    entry[key] = runtime_info[key]

            strategies: List[Dict[str, object]] = []
            if workload_payload is not None:
                for strategy in workload_payload.get("strategies", []):
                    strategies.append(
                        {
                            "name": strategy.get("name"),
                            "supported": bool(strategy.get("supported")),
                            "duration": strategy.get("duration"),
                            "tasks_per_second": strategy.get("tasks_per_second"),
                            "speedup_vs_sequential": strategy.get(
                                "speedup_vs_sequential"
                            ),
                            "reason": strategy.get("reason"),
                        }
                    )
            entry["strategies"] = strategies
            workload_results.append(entry)

        workloads.append(
            {
                "name": workload_name,
                "category": metadata.get("category"),
                "description": metadata.get("description"),
                "results": workload_results,
            }
        )

    versions = [entry.get("python_version", "unknown") for entry in runtime_details]
    implementations = [
        entry.get("python_implementation", "unknown") for entry in runtime_details
    ]

    return {
        "suite": "concurrency",
        "python_versions": versions,
        "python_implementations": implementations,
        "python_runtimes": runtime_details,
        "workloads": workloads,
    }


def _format_concurrency_summary(summary: dict) -> str:
    lines = ["Aggregate concurrency benchmark results:"]
    workloads = summary.get("workloads", [])
    for workload in workloads:
        name = workload.get("name", "unknown workload")
        category = workload.get("category")
        header = f"- {name}"
        if category:
            header += f" [{category}]"
        lines.append(header)
        description = workload.get("description")
        if description:
            lines.append(f"    {description}")
        for entry in workload.get("results", []):
            implementation = entry.get("python_implementation", "unknown")
            version = entry.get("python_version", "unknown")
            runtime_label = f"    {implementation} {version}"
            if entry.get("gil_disabled") is True:
                runtime_label += " [GIL disabled]"
            elif entry.get("gil_disabled") is False:
                runtime_label += " [GIL enabled]"
            tasks = entry.get("tasks")
            workers = entry.get("workers")
            meta_parts = []
            if isinstance(tasks, int):
                meta_parts.append(f"{tasks} tasks")
            if isinstance(workers, int):
                meta_parts.append(f"{workers} workers")
            if meta_parts:
                runtime_label += f" ({', '.join(meta_parts)})"
            lines.append(runtime_label + ":")
            strategies = entry.get("strategies", [])
            if not strategies:
                lines.append("        (no strategy data)")
                continue
            for strategy in strategies:
                name = strategy.get("name", "unknown")
                if not strategy.get("supported", False):
                    reason = strategy.get("reason")
                    if reason:
                        lines.append(f"        {name}: unsupported ({reason})")
                    else:
                        lines.append(f"        {name}: unsupported")
                    continue
                duration = strategy.get("duration")
                tasks_per_second = strategy.get("tasks_per_second")
                speedup = strategy.get("speedup_vs_sequential")
                parts: List[str] = []
                if isinstance(duration, (int, float)):
                    parts.append(f"{duration:.6f}s total")
                if isinstance(tasks_per_second, (int, float)):
                    parts.append(f"{tasks_per_second:.2f} tasks/s")
                if isinstance(speedup, (int, float)):
                    parts.append(f"{speedup:.2f}x vs sequential")
                if parts:
                    lines.append(f"        {name}: " + ", ".join(parts))
                else:
                    lines.append(f"        {name}: supported (no metrics recorded)")
    if not workloads:
        lines.append("(no concurrency benchmark workloads found)")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())

