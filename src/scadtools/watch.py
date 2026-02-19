"""Watch mode: recompile when source files change."""

import sys
import time
from pathlib import Path


def watch_scad(input_file: str, library_prefixes: list[str] | None = None, output: str | None = None) -> None:
    """Watch *input_file* and all its transitive dependencies for changes and recompile on save.

    Requires the ``watchdog`` package (``pip install 'scadtools[watch]'``).
    Exits cleanly on Ctrl+C.
    """
    try:
        from watchdog.events import FileSystemEvent, FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError:
        print(
            "ERROR: watchdog is required for --watch. Install with: pip install 'scadtools[watch]'",
            file=sys.stderr,
        )
        sys.exit(1)

    if output is None:
        print("ERROR: --watch requires --output to be specified.", file=sys.stderr)
        sys.exit(1)

    from scadtools.compiler import compile_scad

    output_path = str(Path(output).resolve())
    watched_dirs: set[str] = set()
    observer = Observer()

    def do_compile() -> set[str]:
        deps: set[str] = set()
        try:
            compile_scad(input_file, library_prefixes, output, deps_out=deps)
            print(f"[watch] Compiled OK — {time.strftime('%H:%M:%S')}")
        except Exception as exc:
            print(f"[watch] ERROR — {exc}", file=sys.stderr)
        return deps

    def _is_output_file(path: str) -> bool:
        return str(Path(path).resolve()) == output_path

    class RecompileHandler(FileSystemEventHandler):
        def on_modified(self, event: FileSystemEvent) -> None:
            path = str(event.src_path)
            if not event.is_directory and path.endswith(".scad") and not _is_output_file(path):
                _recompile()

        def on_created(self, event: FileSystemEvent) -> None:
            path = str(event.src_path)
            if not event.is_directory and path.endswith(".scad") and not _is_output_file(path):
                _recompile()

    def _recompile() -> None:
        new_deps = do_compile()
        _update_watchers(new_deps)

    def _update_watchers(deps: set[str]) -> None:
        dirs = {str(Path(f).parent.resolve()) for f in deps}
        dirs.add(str(Path(input_file).parent.resolve()))
        for d in dirs - watched_dirs:
            observer.schedule(RecompileHandler(), d, recursive=False)
            watched_dirs.add(d)
            print(f"[watch] Watching: {d}")

    initial_deps = do_compile()
    _update_watchers(initial_deps)

    observer.start()
    print("[watch] Press Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
