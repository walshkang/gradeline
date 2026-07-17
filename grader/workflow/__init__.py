__all__ = ["main", "build_parser"]

def __getattr__(name):
    if name in ("main", "build_parser"):
        from ..workflow_cli import main, build_parser
        if name == "main":
            return main
        return build_parser
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
