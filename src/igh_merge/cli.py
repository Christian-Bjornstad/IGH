from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .io import ValidationError
from .privacy import PrivacyError
from .service import MergeService


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Merge local IGHV-SHM Leader/FR1 results")
    parser.add_argument("run_folder", type=Path, help="Run folder with Leader and FR1 output")
    parser.add_argument("--output", type=Path, help="Target file. Default: YYYY_MM_DD_merged.xlsx in run folder")
    parser.add_argument("--expected-samples", type=int, default=24)
    parser.add_argument("--allow-count-warning", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument(
        "--highlight-yellow-rows",
        action="store_true",
        help="Highlight app's preliminary yellow Leader candidates in Excel",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        service = MergeService()
        result = service.process(args.run_folder, args.expected_samples)
        if result.manifest.warnings and not args.allow_count_warning:
            for warning in result.manifest.warnings:
                print(f"WARNING: {warning}", file=sys.stderr)
            print("Use --allow-count-warning to accept the deviation.", file=sys.stderr)
            return 2
        output = args.output or (
            result.manifest.run_directory / f"{result.manifest.run_date}_merged.xlsx"
        )
        written = service.export(
            result,
            output,
            overwrite=args.overwrite,
            highlight_functional_rows=args.highlight_yellow_rows,
        )
        print(f"Wrote {len(result.rows)} rows to {written}")
        print(f"Controls: {result.qc.error_count} errors.")
        return 0
    except (ValidationError, PrivacyError, FileExistsError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
