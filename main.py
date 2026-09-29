"""Run the uploaded Quran bot source from the workspace root."""

from pathlib import Path
from runpy import run_path


run_path(
    str(Path(__file__).parent / "attached_assets" / "main_1790693559152.py"),
    run_name="__main__",
)