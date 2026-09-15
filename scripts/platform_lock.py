"""Small cross-platform advisory file-lock helper used by merge operations."""

from __future__ import annotations

import os


if os.name == "nt":
    import msvcrt

    def try_lock(stream) -> None:
        """Acquire a one-byte, non-blocking lock or raise BlockingIOError."""
        stream.seek(0, os.SEEK_END)
        if stream.tell() == 0:
            stream.write("\0")
            stream.flush()
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as error:
            raise BlockingIOError(str(error)) from error

    def unlock(stream) -> None:
        stream.seek(0)
        try:
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def try_lock(stream) -> None:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def unlock(stream) -> None:
        fcntl.flock(stream, fcntl.LOCK_UN)
