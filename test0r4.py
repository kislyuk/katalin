"""
Manages environment yaml file paths.

clrenv expects a base environment file (environment.yaml) and zero or more overlay
files.

Without configuration (via env vars) looks for an environment.yaml in the cwd or one of
its parents. This can be set explicitly by setting CLRENV_PATH.

Overlay files can be specified with the CLRENV_OVERLAY_PATH env var. Multiple overlays
can be specified with a colon (:) delimiter. Overlays that do not exist will be ignored.

Values in overlay files take precedence over values in the base file and mask its
values. Note that this is a different mechanism from the base/"mode" sections in each
file which also overlay values. See a full explanation in the docs for EnvReader#read.
"""
import logging
from os import environ
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEBUG_MODE = environ.get("CLRENV_DEBUG", "").lower() in ("true", "1")


def environment_paths() -> Tuple[Path, ...]:
    """Returns a sequence of yaml file paths that constitute the current enviroment.

    Files are listed in decreasing order of precedence (overlays first). Will
    not return an empty list. All returned path are guaranteed to exist.

    Raises an exception if the base environment file can not be found.
    """
    result: List[Path] = []
    result.extend(_resolve_paths(environ.get("CLRENV_OVERLAY_PATH")))
    base_path = _resolve_path(environ.get("CLRENV_PATH"))
    if not base_path:
        base_path = _find_in_cwd_or_parents("environment.yaml")
    if not base_path or not base_path.is_file():
        raise ValueError(
            f"Base environment file (CLRENV_PATH) could not be located. {base_path if base_path else ''}"
        )
    result.append(base_path)
    return tuple(result)


def _resolve_path(path: Optional[str]) -> Optional[Path]:
    """Resolves a user provided path. Returns None for empty string.
    Does not confirm the file exists.
    """
    if not path:
        return None
    return Path(path).expanduser().absolute()


def _resolve_paths(paths: Optional[str]) -> Iterable[Path]:
    """Resolves a user provided, colon seperated, list of paths.

    Will drop values that do not exist."""
    result = []
    for path in paths.split(":") if paths else []:
        resolved = _resolve_path(path)
        if resolved and resolved.is_file():
            result.append(resolved)
        elif DEBUG_MODE:
            logging.warning(f'Could not find "{path}" {resolved}, ignoring it.')
    return result


def _find_in_cwd_or_parents(name: str) -> Optional[Path]:
    """Finds a file with the given name starting in the cwd and working up to root."""
    for parent in (Path().absolute() / name).parents:
        path = parent / name
        if path.is_file():
            return path
    return None
