"""BSON → NDJSON converter for the mongodump-lightning load path.

Reads `*.bson` files produced by `mongodump`, applies BSON-type-aware JSON
serialization (matching the check-phase canonicalization), and writes NDJSON
via fsspec — cloud-agnostic staging.
"""

from __future__ import annotations

import json
import logging
import stat
import subprocess
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

from tishift_mongodb.config import TiShiftConfig
from tishift_mongodb.core.check.hash_diff import canonicalize
from tishift_mongodb.storage import fs_for, join, parse_url


log = logging.getLogger(__name__)


@contextmanager
def _mongodump_config_file(uri: str) -> Iterator[Path]:
    """Write the Mongo URI to a chmod-0600 temp config file for mongodump.

    Why: passing the URI as `--uri=...` puts the password (embedded in the
    URI) into the process argv, where it's visible via /proc/<pid>/cmdline
    and `ps -ef` to other users on the same host for the duration of the
    dump. Using `--config=<file>` keeps the URI off the command line.

    The temp file is created with mode 0600 (owner read/write only) and
    deleted unconditionally on exit.
    """
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", prefix="tishift-mongodump-",
        delete=False, encoding="utf-8",
    )
    try:
        path = Path(tmp.name)
        # mongodump config-file format (YAML): supports `uri:` key.
        tmp.write(f"uri: {json.dumps(uri)}\n")
        tmp.close()
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        log.debug("Wrote mongodump config to %s (mode 600)", path)
        yield path
    finally:
        try:
            Path(tmp.name).unlink(missing_ok=True)
        except OSError as e:
            log.warning("Failed to delete mongodump config file %s: %s", tmp.name, e)


@dataclass
class MongodumpResult:
    dump_dir: Path
    collections: list[str]
    oplog_path: Path | None


def run_mongodump(
    cfg: TiShiftConfig, *, dump_dir: str | Path
) -> MongodumpResult:
    """Invoke mongodump. Returns paths to BSON files for each collection.

    Security:
    - Args are a list, no shell=True, no string concatenation.
    - The Mongo URI (which embeds the password) is written to a chmod-0600
      temp config file and passed via `--config=path`, NOT via `--uri=$URI`
      in argv — argv is world-readable via /proc/<pid>/cmdline.
    """
    dump_path = Path(dump_dir)
    dump_path.mkdir(parents=True, exist_ok=True)

    with _mongodump_config_file(cfg.source.uri) as config_file:
        cmd = [
            "mongodump",
            f"--config={config_file}",
            f"--db={cfg.source.database}",
            f"--out={dump_path}",
            f"--numParallelCollections={cfg.load.mongodump.parallel_collections}",
        ]
        if cfg.load.mongodump.use_oplog:
            cmd.append("--oplog")

        log.info("Running mongodump → %s (URI via chmod-0600 config file)", dump_path)
        proc = subprocess.run(cmd, check=False)
        if proc.returncode != 0:
            raise RuntimeError(f"mongodump failed with exit code {proc.returncode}")

    db_dir = dump_path / cfg.source.database
    collections = [
        p.stem for p in db_dir.glob("*.bson") if not p.name.endswith(".metadata.json")
    ]
    oplog = dump_path / "oplog.bson"

    return MongodumpResult(
        dump_dir=db_dir,
        collections=collections,
        oplog_path=oplog if oplog.exists() else None,
    )


def _bson_doc_to_canonical_dict(doc: dict[str, Any]) -> dict[str, Any]:
    """Apply canonicalize to a BSON-decoded document, preserving the _id at top level."""
    out: dict[str, Any] = {}
    for k, v in doc.items():
        out[k] = canonicalize(v)
    # Lightning expects 'id' column key in NDJSON for the PK
    if "_id" in out:
        out["id"] = (out["_id"]["$oid"] if isinstance(out["_id"], dict) and "$oid" in out["_id"]
                     else out["_id"])
    return out


def convert_bson_to_ndjson(
    bson_path: Path,
    out_url: str,
    *,
    chunk_size: int = 10_000,
) -> int:
    """Stream one collection's BSON file to NDJSON at the staging URL.

    Returns the number of documents converted.
    """
    from bson import decode_file_iter  # type: ignore[import-not-found]

    fs = fs_for(out_url)
    _, remainder = parse_url(out_url)

    count = 0
    part_idx = 0
    chunk_lines: list[str] = []

    with open(bson_path, "rb") as bson_file:
        for doc in decode_file_iter(bson_file):
            canonical = _bson_doc_to_canonical_dict(doc)
            chunk_lines.append(json.dumps(canonical, separators=(",", ":")))
            count += 1
            if len(chunk_lines) >= chunk_size:
                part_path = f"{remainder.rstrip('/')}/part-{part_idx:05d}.ndjson"
                with fs.open(part_path, "wb") as f:
                    f.write(("\n".join(chunk_lines) + "\n").encode("utf-8"))
                chunk_lines.clear()
                part_idx += 1

    if chunk_lines:
        part_path = f"{remainder.rstrip('/')}/part-{part_idx:05d}.ndjson"
        with fs.open(part_path, "wb") as f:
            f.write(("\n".join(chunk_lines) + "\n").encode("utf-8"))

    log.info("Converted %s → %s (%d docs)", bson_path.name, out_url, count)
    return count


def run_mongodump_to_staging(
    cfg: TiShiftConfig, *, local_dump_dir: str | Path = "/tmp/tishift-mongodump"
) -> dict[str, int]:
    """End-to-end: mongodump → BSON-to-NDJSON via fsspec → staging."""
    dump_result = run_mongodump(cfg, dump_dir=local_dump_dir)

    results: dict[str, int] = {}
    for collection in dump_result.collections:
        bson_path = dump_result.dump_dir / f"{collection}.bson"
        staging_url = join(cfg.load.staging.base_url, collection)
        n = convert_bson_to_ndjson(bson_path, staging_url)
        results[collection] = n
    return results
