"""CLI entry point for the OpenSCAD compiler."""

import argparse
import sys

from scadtools.compiler import compile_scad


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="scad-compiler",
        description="Compile OpenSCAD files by inlining use/include dependencies into a single self-contained file.",
    )
    parser.add_argument("input_file", help="Input SCAD file to process")
    parser.add_argument(
        "-l",
        "--library-prefix",
        action="append",
        default=[],
        help="Library prefixes to preserve (can be used multiple times)",
    )
    parser.add_argument("-o", "--output", help="Output file (default: stdout)")
    parser.add_argument(
        "--watch",
        action="store_true",
        help="Watch source files for changes and recompile automatically (requires --output)",
    )

    args = parser.parse_args()

    if args.watch:
        from scadtools.watch import watch_scad

        watch_scad(args.input_file, args.library_prefix, args.output)
        return

    try:
        result = compile_scad(args.input_file, args.library_prefix, args.output)
    except FileNotFoundError as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

    # If no output file specified, print to stdout
    if not args.output:
        print(result)


if __name__ == "__main__":
    main()
