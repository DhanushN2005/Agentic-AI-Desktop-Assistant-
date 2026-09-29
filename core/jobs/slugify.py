"""Safe workspace folder slugification for Windows and POSIX."""
from __future__ import annotations

import os
import re
import unicodedata

_WIN_RESERVED = {
    "con", "prn", "aux", "nul",
    *(f"com{i}" for i in range(1, 10)),
    *(f"lpt{i}" for i in range(1, 10)),
}


def slugify_job_name(title: str, max_chars: int = 50) -> str:
    """Produce a safe directory name component.

    - Replaces non-ASCII chars with ASCII equivalents
    - Strips invalid filesystem chars (<>:"/\\|?*)
    - Avoids Windows reserved device names (CON, NUL, etc.)
    - Removes trailing dots and spaces
    - Limits length to max_chars
    """
    if not title:
        return "project"

    # NFKD normalization -> ASCII fallback
    normalized = unicodedata.normalize("NFKD", title)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")

    # Replace invalid/special characters with a hyphen
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", ascii_text).strip("-").lower()

    # Avoid empty slug
    if not slug:
        slug = "project"

    # Handle Windows reserved names (and reserved names with extensions)
    stem = slug.split("-")[0]
    if stem in _WIN_RESERVED or slug in _WIN_RESERVED:
        slug = f"p-{slug}"

    # Truncate to max_chars safely
    if len(slug) > max_chars:
        slug = slug[:max_chars].rstrip("-")

    # Strip any trailing dots or spaces which Windows rejects
    slug = slug.rstrip(". ")
    return slug or "project"


def create_job_workspace(root: str, title: str, job_id: str) -> str:
    """Create a unique per-job workspace directory under root.

    Format: <WORKSPACE_ROOT>/<slugified-name>-<short-id>/
    Never overwrites an existing folder; appends a numeric suffix if needed.
    """
    os.makedirs(root, exist_ok=True)
    slug = slugify_job_name(title)
    short_id = str(job_id)[:8]
    base_folder_name = f"{slug}-{short_id}"

    target_dir = os.path.join(root, base_folder_name)
    suffix = 1
    while os.path.exists(target_dir):
        suffix += 1
        target_dir = os.path.join(root, f"{base_folder_name}-{suffix}")

    os.makedirs(target_dir, exist_ok=True)
    return os.path.realpath(target_dir)
