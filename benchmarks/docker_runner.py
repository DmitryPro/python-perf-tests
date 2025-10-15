"""Utilities for building and executing all benchmark Docker images.

In addition to orchestrating ``docker build`` / ``docker run`` cycles this
module can persist benchmark outputs to a shared directory and produce a simple
aggregated summary across Python versions.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence, Tuple

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKER_ROOT = REPO_ROOT / "docker"


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
) -> List[DockerTarget]:
    """Build and run all Docker images.

    Returns the ordered list of processed :class:`DockerTarget` objects.
    """

    targets = discover_targets(docker_root)

    if results_dir is not None:
        results_dir.mkdir(parents=True, exist_ok=True)

    if run_cmd is not None:
        resolved_run_cmd = run_cmd
    elif iterations is not None or repeat is not None:
        resolved_run_cmd = _build_benchmark_command(iterations, repeat)
    else:
        resolved_run_cmd = None

    for target in targets:
        if not skip_build:
            build_image(target, context=context, dry_run=dry_run)
        if not skip_run:
            run_container(
                target,
                dry_run=dry_run,
                run_cmd=resolved_run_cmd,
                results_dir=results_dir,
            )

    if (
        not skip_run
        and not dry_run
        and aggregate
        and results_dir is not None
    ):
        summary_text = summarize_results(results_dir)
        if summary_text:
            print(summary_text)
    return targets


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
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
        default=REPO_ROOT / "results",
        help="Directory on the host where benchmark results are stored",
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
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    run_cmd = shlex.split(args.run_cmd) if args.run_cmd else None

    if run_cmd is not None and (args.iterations is not None or args.repeat is not None):
        print("Error: --run-cmd cannot be combined with --iterations/--repeat overrides")
        return 1

    try:
        execute(
            context=args.context,
            docker_root=args.docker_root,
            skip_build=args.skip_build,
            skip_run=args.skip_run,
            dry_run=args.dry_run,
            run_cmd=run_cmd,
            results_dir=args.results_dir,
            aggregate=not args.no_aggregate,
            iterations=args.iterations,
            repeat=args.repeat,
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


def summarize_results(results_dir: Path) -> str | None:
    """Aggregate all benchmark JSON files and return a human-readable summary.

    A ``summary.json`` file will also be written next to the inputs containing
    structured data for further processing.
    """

    payloads = list(_load_payloads(results_dir))
    if not payloads:
        return None

    sorted_payloads = sorted(
        payloads,
        key=lambda payload: _version_key(payload.get("python_version", "")),
    )
    summary = _aggregate_payloads(sorted_payloads)
    (results_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    return _format_summary(summary)


def _load_payloads(results_dir: Path) -> Iterable[dict]:
    pattern = "benchmarks-python-*.json"
    for path in sorted(results_dir.glob(pattern)):
        try:
            yield json.loads(path.read_text())
        except json.JSONDecodeError:
            print(f"Warning: could not parse benchmark output '{path}'")


def _version_key(version: str) -> Tuple[int, ...]:
    parts: List[int] = []
    for part in version.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            break
    return tuple(parts)


def _aggregate_payloads(payloads: Sequence[dict]) -> dict:
    case_order: List[str] = []
    seen_cases = set()
    for payload in payloads:
        for case in payload.get("cases", []):
            name = case.get("name")
            if name and name not in seen_cases:
                case_order.append(name)
                seen_cases.add(name)

    versions = [payload.get("python_version", "unknown") for payload in payloads]
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
                    "python_version": payload.get("python_version", "unknown"),
                    "iterations": payload.get("iterations"),
                    "repeat": payload.get("repeat"),
                    "mean": case_data.get("mean") if case_data else None,
                    "stdev": case_data.get("stdev") if case_data else None,
                }
            )
        cases.append({"name": case_name, "results": results})

    return {"python_versions": versions, "cases": cases}


def _format_summary(summary: dict) -> str:
    lines = ["Aggregate benchmark results (mean ± stdev seconds per run):"]
    for case in summary.get("cases", []):
        lines.append(f"- {case['name']}")
        for entry in case.get("results", []):
            version = entry.get("python_version", "unknown")
            mean = entry.get("mean")
            stdev = entry.get("stdev")
            iterations = entry.get("iterations")
            repeat = entry.get("repeat")
            if mean is None:
                lines.append(f"    {version}: no data")
            else:
                meta_parts = []
                if isinstance(iterations, int):
                    meta_parts.append(f"{iterations} iterations")
                if isinstance(repeat, int):
                    meta_parts.append(f"{repeat} repeats")
                meta = f" ({', '.join(meta_parts)})" if meta_parts else ""
                lines.append(f"    {version}{meta}: {mean:.6f}s ± {stdev:.6f}s total")
    if not summary.get("cases"):
        lines.append("(no benchmark cases found)")
    return "\n".join(lines)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
