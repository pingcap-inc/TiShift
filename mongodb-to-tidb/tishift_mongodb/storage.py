"""Cloud-agnostic storage URI handling.

Wraps fsspec so the same code paths work against s3://, gs://, azure://,
or local://. Each cloud-specific backend is an optional install extra.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from fsspec.spec import AbstractFileSystem  # type: ignore[import-not-found]


log = logging.getLogger(__name__)


_BACKEND_SCHEMES = {
    "s3": "s3",
    "gs": "gs",
    "azure": "abfs",     # adlfs registers as "abfs" or "az"
    "az": "abfs",
    "abfs": "abfs",
    "local": "file",
    "file": "file",
}


class StorageBackendError(RuntimeError):
    """Raised when a backend is requested but its install extra is missing."""


def parse_url(url: str) -> tuple[str, str]:
    """Split a TiShift staging URL into (scheme, remainder).

    Accepts: s3://bucket/prefix, gs://bucket/prefix, azure://container/prefix,
    local:///abs/path, file:///abs/path. Note s3 has a digit — regex allows it.
    """
    match = re.match(r"^([a-z][a-z0-9]*)://(.+)$", url)
    if not match:
        raise ValueError(f"unrecognized storage URL: {url}")
    scheme = match.group(1).lower()
    if scheme not in _BACKEND_SCHEMES:
        raise ValueError(
            f"unsupported storage scheme {scheme!r} in {url!r}; "
            f"expected one of: {sorted(set(_BACKEND_SCHEMES.values()))}"
        )
    return scheme, match.group(2)


def fs_for(url: str) -> "AbstractFileSystem":
    """Return an fsspec filesystem for the given URL's scheme.

    Lazy imports — only the requested backend's package is loaded. If the
    extra isn't installed, raises StorageBackendError with the install hint.
    """
    scheme, _ = parse_url(url)
    canonical = _BACKEND_SCHEMES[scheme]

    try:
        import fsspec  # type: ignore[import-not-found]
    except ImportError as e:
        raise StorageBackendError(
            "fsspec not installed. Install the core package: "
            "pip install tishift-mongodb"
        ) from e

    extras_hint = {
        "s3": "pip install tishift-mongodb[s3]",
        "gs": "pip install tishift-mongodb[gcs]",
        "abfs": "pip install tishift-mongodb[azure]",
        "file": None,
    }

    try:
        return fsspec.filesystem(canonical)
    except (ImportError, ValueError) as e:
        hint = extras_hint.get(canonical)
        msg = f"failed to instantiate fsspec backend {canonical!r}: {e}"
        if hint:
            msg += f"\nInstall the backend extra: {hint}"
        raise StorageBackendError(msg) from e


def join(base_url: str, *parts: str) -> str:
    """Join base_url with additional path components.

    Equivalent to os.path.join for the path portion while preserving the
    scheme://host part.
    """
    scheme, remainder = parse_url(base_url)
    rem = remainder.rstrip("/")
    for p in parts:
        rem = rem + "/" + p.strip("/")
    return f"{scheme}://{rem}"


def ensure_writable(url: str) -> None:
    """Probe writability of the staging location.

    Writes and deletes a single small object. Used by preflight.
    Raises StorageBackendError on failure.
    """
    fs = fs_for(url)
    _, remainder = parse_url(url)
    probe_path = remainder.rstrip("/") + "/.tishift-preflight-probe"
    try:
        with fs.open(probe_path, "wb") as f:
            f.write(b"ok")
        fs.delete(probe_path)
    except Exception as e:
        raise StorageBackendError(
            f"staging URL {url!r} is not writable: {e}"
        ) from e


def list_files(url: str) -> list[str]:
    """List files under the staging URL."""
    fs = fs_for(url)
    _, remainder = parse_url(url)
    return list(fs.find(remainder))
