"""python -m engine [setup|check]"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    cmd = argv[0] if argv else "run"
    if cmd in ("-h", "--help", "help"):
        print("Usage: python -m engine [run|setup|check]")
        print("  run     start the server (default)")
        print("  setup   create .env if missing and print LLM plug-in snippets")
        print("  check   live Mode 1 search check (scripts/check_search.py)")
        return 0
    if cmd == "setup":
        from .setup import run_setup

        return run_setup(argv[1:])
    if cmd == "check":
        from pathlib import Path
        import runpy

        script = Path(__file__).resolve().parents[1] / "scripts" / "check_search.py"
        runpy.run_path(str(script), run_name="__main__")
        return 0
    if cmd != "run":
        # Unknown first arg — treat as uvicorn passthrough only if it looks like a flag.
        if not cmd.startswith("-"):
            print(f"Unknown command: {cmd}. Try: python -m engine setup", file=sys.stderr)
            return 2

    import uvicorn

    from .config import settings
    from .connect import print_banner

    print_banner()
    uvicorn.run(
        "engine.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
