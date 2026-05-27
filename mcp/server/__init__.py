from pathlib import Path
import sys


def _extend_sdk_path() -> None:
    local_package = Path(__file__).resolve().parent
    for entry in sys.path:
        if not entry:
            continue
        try:
            candidate = (Path(entry).resolve() / "mcp" / "server")
        except OSError:
            continue
        if candidate == local_package:
            continue
        if (candidate / "lowlevel").exists() or (candidate / "lowlevel.py").exists():
            __path__.append(str(candidate))
            return


_extend_sdk_path()
