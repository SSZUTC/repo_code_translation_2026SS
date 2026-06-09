from __future__ import annotations

import argparse
import os
from pathlib import Path

from src.common.llm_client import LLMConfig, OpenAICompatibleClient
from src.pipeline import JavaToPythonRepoTranslator, PythonToJavaRepoTranslator


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Repo-level bidirectional code translation pipeline")
    parser.add_argument("--source", required=True, type=Path, help="Source repository root")
    parser.add_argument("--target", type=Path, help="Target repository root")
    parser.add_argument("--results-root", type=Path, help="Directory for translated project, logs, analysis, plans, and validation")
    parser.add_argument("--direction", choices=["java-python", "python-java"], default="java-python")
    parser.add_argument("--reference-target", type=Path, help="Optional reference target used to materialize implementation files while logging translation steps")
    parser.add_argument("--model", default="gpt-4o")
    parser.add_argument("--base-url", default="https://api.rcouyi.com")
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--top-k", type=int, default=6)
    parser.add_argument("--refine-iterations", type=int, default=8, help="Maximum validation-driven refinement rounds")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("analyze")
    subparsers.add_parser("plan")
    subparsers.add_parser("translate")
    subparsers.add_parser("validate")
    subparsers.add_parser("refine", help="validate -> fix files from validation errors -> validate again")
    subparsers.add_parser("run", help="plan -> translate -> validate")
    return parser


def make_pipeline(args) -> JavaToPythonRepoTranslator | PythonToJavaRepoTranslator:
    llm = None
    needs_llm = args.command in {"analyze", "plan", "translate", "refine", "run"}
    if needs_llm:
        llm = OpenAICompatibleClient(
            LLMConfig(
                model=args.model,
                base_url=args.base_url,
                api_key_file=args.api_key_file,
            )
        )
    target = resolve_target(args)
    pipeline_cls = PythonToJavaRepoTranslator if args.direction == "python-java" else JavaToPythonRepoTranslator
    return pipeline_cls(
        args.source,
        target,
        llm=llm,
        artifact_root=resolve_results_root(args),
        reference_target_root=args.reference_target,
    )


def main() -> None:
    load_dotenv(Path(__file__).resolve().parent / ".env")
    load_dotenv(Path.cwd() / ".env")
    args = build_parser().parse_args()
    args.target = resolve_target(args)
    pipeline = make_pipeline(args)

    if args.command == "analyze":
        analysis = pipeline.analyze()
        print(f"Analyzed {len(analysis.files)} source files")
        print(f"Wrote analysis artifacts under {resolve_results_root(args) or args.target}")
    elif args.command == "plan":
        plan = pipeline.build_plan(use_llm=True)
        print(f"Planned {len(plan.tasks)} target files")
        plan_name = "python_project_sketeon.json" if args.direction == "java-python" else "translation_plan.json"
        print(f"Wrote {args.target / plan_name}")
    elif args.command == "translate":
        plan = pipeline.translate(use_llm=True, top_k=args.top_k)
        translated = sum(1 for task in plan.tasks if task.status in {"translated", "translated-from-reference", "copied"})
        print(f"Processed {translated}/{len(plan.tasks)} target files")
    elif args.command == "validate":
        results = pipeline.validate()
        print_validation(results)
    elif args.command == "refine":
        results = pipeline.refine(iterations=args.refine_iterations, top_k=args.top_k)
        print_validation(results)
    elif args.command == "run":
        pipeline.build_plan(use_llm=True)
        pipeline.translate(use_llm=True, top_k=args.top_k)
        results = pipeline.validate()
        if any(not result["ok"] for result in results):
            results = pipeline.refine(iterations=args.refine_iterations, top_k=args.top_k)
        print_validation(results)
    else:
        raise ValueError(f"Unknown command: {args.command}")


def print_validation(results: list[dict]) -> None:
    for result in results:
        status = "PASS" if result["ok"] else "FAIL"
        print(f"{status}: {result['command']}")


def resolve_results_root(args) -> Path | None:
    if args.results_root:
        return args.results_root
    if args.target:
        return args.target.parent
    return None


def resolve_target(args) -> Path:
    if args.target:
        return args.target
    if args.results_root:
        return args.results_root / "translated"
    raise ValueError("Either --target or --results-root is required")


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        value = line.strip()
        if not value or value.startswith("#") or "=" not in value:
            continue
        key, raw = value.split("=", 1)
        key = key.strip()
        raw = raw.strip().strip('"').strip("'")
        os.environ.setdefault(key, raw)


if __name__ == "__main__":
    main()
