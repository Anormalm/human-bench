"""Compatibility entry point; the runner also ships in the installed package."""
from shuorenhua_bench.response_runner import main, render_prompt, run

__all__ = ["main", "render_prompt", "run"]

if __name__ == "__main__":
    main()
