"""Start the Quran bot from either the uploaded-assets layout or a flat deploy."""

from pathlib import Path
from runpy import run_path


BASE_DIR = Path(__file__).resolve().parent
SOURCE_CANDIDATES = (
    BASE_DIR / "attached_assets" / "main_1790693559152.py",
    BASE_DIR / "main_1790693559152.py",
)

source = next((path for path in SOURCE_CANDIDATES if path.is_file()), None)
if source is None:
    searched = "\n".join(f"- {path}" for path in SOURCE_CANDIDATES)
    raise FileNotFoundError(
        "Bot source file is missing. Upload the complete project ZIP. "
        f"Paths checked:\n{searched}"
    )

run_path(str(source), run_name="__main__")