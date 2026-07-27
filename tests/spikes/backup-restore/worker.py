"""Crash-injection worker for SPIKE-BACKUP-RESTORE-001.

The parent process terminates this worker only after a flushed checkpoint
marker proves that the requested failpoint has been reached.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sqlite3
from pathlib import Path

from _spike_harness import (
    FORMAT_ID,
    INCOMPLETE_NAME,
    checkpoint_and_block,
    stage_restore,
    write_json,
)


def interrupt_database_backup(arguments: argparse.Namespace) -> int:
    staging = Path(arguments.staging)
    staging.mkdir(parents=True, exist_ok=False)
    write_json(
        staging / INCOMPLETE_NAME,
        {
            "status": "incomplete",
            "format_id": FORMAT_ID,
            "failpoint": "during_database_backup",
        },
    )
    destination_path = staging / "database" / "snapshot.sqlite3.partial"
    destination_path.parent.mkdir(parents=True)
    source_uri = Path(arguments.source_database).resolve().as_uri() + "?mode=ro"
    source = sqlite3.connect(source_uri, uri=True)
    destination = sqlite3.connect(destination_path)
    callbacks = 0

    def progress(status: int, remaining: int, total: int) -> None:
        nonlocal callbacks
        callbacks += 1
        if (
            callbacks >= int(arguments.after_callbacks)
            and remaining > 0
        ):
            checkpoint_and_block(
                Path(arguments.checkpoint),
                {
                    "checkpoint": "during_database_backup",
                    "callbacks": callbacks,
                    "status": status,
                    "remaining_pages": remaining,
                    "total_pages": total,
                },
            )

    try:
        source.backup(
            destination,
            pages=1,
            progress=progress,
            sleep=0.001,
        )
        destination.commit()
    finally:
        destination.close()
        source.close()
    return 4


def interrupt_blob_copy(arguments: argparse.Namespace) -> int:
    source = Path(arguments.source)
    partial = Path(arguments.partial)
    final = Path(arguments.final)
    partial.parent.mkdir(parents=True, exist_ok=True)
    final.parent.mkdir(parents=True, exist_ok=True)
    chunks = 0
    with source.open("rb") as input_handle, partial.open("wb") as output_handle:
        while True:
            chunk = input_handle.read(int(arguments.chunk_size))
            if not chunk:
                break
            output_handle.write(chunk)
            output_handle.flush()
            os.fsync(output_handle.fileno())
            chunks += 1
            if chunks >= int(arguments.after_chunks):
                checkpoint_and_block(
                    Path(arguments.checkpoint),
                    {
                        "checkpoint": "during_blob_copy",
                        "chunks_written": chunks,
                        "partial_bytes": partial.stat().st_size,
                    },
                )
    shutil.move(partial, final)
    return 4


def interrupt_restore(arguments: argparse.Namespace) -> int:
    staging = stage_restore(
        Path(arguments.bundle),
        Path(arguments.install_root),
        arguments.generation_name,
    )
    checkpoint_and_block(
        Path(arguments.checkpoint),
        {
            "checkpoint": "before_restore_activation",
            "staging_name": staging.name,
        },
    )
    return 4


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="mode", required=True)

    backup = subparsers.add_parser("interrupt-database-backup")
    backup.add_argument("--source-database", required=True)
    backup.add_argument("--staging", required=True)
    backup.add_argument("--checkpoint", required=True)
    backup.add_argument("--after-callbacks", required=True, type=int)
    backup.set_defaults(handler=interrupt_database_backup)

    blob = subparsers.add_parser("interrupt-blob-copy")
    blob.add_argument("--source", required=True)
    blob.add_argument("--partial", required=True)
    blob.add_argument("--final", required=True)
    blob.add_argument("--checkpoint", required=True)
    blob.add_argument("--chunk-size", required=True, type=int)
    blob.add_argument("--after-chunks", required=True, type=int)
    blob.set_defaults(handler=interrupt_blob_copy)

    restore = subparsers.add_parser("interrupt-restore")
    restore.add_argument("--bundle", required=True)
    restore.add_argument("--install-root", required=True)
    restore.add_argument("--generation-name", required=True)
    restore.add_argument("--checkpoint", required=True)
    restore.set_defaults(handler=interrupt_restore)
    return parser


def main() -> int:
    arguments = build_parser().parse_args()
    return int(arguments.handler(arguments))


if __name__ == "__main__":
    raise SystemExit(main())
