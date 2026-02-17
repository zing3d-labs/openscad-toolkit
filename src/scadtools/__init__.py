from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("scadtools")
except PackageNotFoundError:
    __version__ = "0.0.0-dev"

from scadtools.compiler import compile_scad

__all__ = ["compile_scad", "__version__"]
