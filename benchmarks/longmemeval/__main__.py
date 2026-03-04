"""LongMemEval 벤치마크 CLI 엔트리포인트

Usage:
    python -m benchmarks.longmemeval run [--config config.yaml]
    python -m benchmarks.longmemeval evaluate --results results/en_session.jsonl
    python -m benchmarks.longmemeval report --results results/en_session.jsonl
    python -m benchmarks.longmemeval translate [--phase 1] [--output data/longmemeval_ko.json]
"""

import argparse
import asyncio
import logging
import sys


def main() -> None:
    parser = argparse.ArgumentParser(
        description="LongMemEval benchmark for mem-mesh"
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )

    subparsers = parser.add_subparsers(dest="command", help="Command")

    # run
    run_parser = subparsers.add_parser(
        "run", help="Run full benchmark pipeline"
    )
    run_parser.add_argument(
        "--config",
        default=None,
        help="Config YAML path (default: built-in config.yaml)",
    )
    run_parser.add_argument(
        "--max-questions",
        type=int,
        default=None,
        help="Maximum number of questions to process",
    )

    # evaluate
    eval_parser = subparsers.add_parser(
        "evaluate", help="Re-evaluate existing results"
    )
    eval_parser.add_argument(
        "--results", required=True, help="JSONL results file path"
    )
    eval_parser.add_argument(
        "--config", default=None, help="Config YAML path"
    )

    # report
    report_parser = subparsers.add_parser(
        "report", help="Generate report from results"
    )
    report_parser.add_argument(
        "--results", required=True, help="JSONL results file path"
    )
    report_parser.add_argument(
        "--config", default=None, help="Config YAML path"
    )

    # translate
    translate_parser = subparsers.add_parser(
        "translate", help="Translate dataset to Korean"
    )
    translate_parser.add_argument(
        "--config", default=None, help="Config YAML path"
    )
    translate_parser.add_argument(
        "--phase",
        type=int,
        default=1,
        choices=[1, 2, 3],
        help="Translation phase (1=QA, 2=evidence sessions, 3=full haystack)",
    )
    translate_parser.add_argument(
        "--output",
        default=None,
        help="Output file path",
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # 로깅 설정
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.command == "run":
        _run_benchmark(args)
    elif args.command == "evaluate":
        _run_evaluate(args)
    elif args.command == "report":
        _run_report(args)
    elif args.command == "translate":
        _run_translate(args)


def _run_benchmark(args: argparse.Namespace) -> None:
    from .adapter import BenchmarkRunner
    from .config import load_config

    config = load_config(args.config)
    if args.max_questions is not None:
        config.execution.max_questions = args.max_questions

    runner = BenchmarkRunner(config)
    asyncio.run(runner.run())


def _run_evaluate(args: argparse.Namespace) -> None:
    from .adapter import run_evaluate_only
    from .config import load_config

    config = load_config(args.config)
    asyncio.run(run_evaluate_only(config, args.results))


def _run_report(args: argparse.Namespace) -> None:
    from .adapter import run_report_only
    from .config import load_config

    config = load_config(args.config)
    asyncio.run(run_report_only(config, args.results))


def _run_translate(args: argparse.Namespace) -> None:
    from .config import load_config
    from .translator import translate_dataset

    config = load_config(args.config)
    asyncio.run(
        translate_dataset(
            config, phase=args.phase, output_path=args.output
        )
    )


if __name__ == "__main__":
    main()
