"""Immutable, content-addressed proposal generations with private staging."""
from contextlib import contextmanager
from pathlib import Path
import os
import shutil
import tempfile

from ..annotation_io import content_digest, sha256
from ..quality_benchmark import write_report
from .contracts import load_proposal_set


def cache_key(identity, input_digests, provider, settings):
    return content_digest({"contract": 1, "identity": identity, "input_digests": input_digests,
                           "provider": provider, "settings": settings})


class ProposalCache:
    def __init__(self, root):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key, cancelled=lambda: False):
        sha256(key, "proposal generation key")
        directory = self.root / key
        if not directory.exists():
            return None
        manifest = load_proposal_set(directory, cancelled=cancelled)
        if manifest["cache_key"] != key:
            raise ValueError("Recognition cache key disagrees with its immutable generation")
        return directory, manifest

    @contextmanager
    def stage(self):
        # The owner must close all mappings before this private directory is
        # removed on Windows. No saved project/model path is ever touched.
        temporary = Path(tempfile.mkdtemp(prefix=".proposal-stage-", dir=self.root))
        try:
            yield temporary
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def publish(self, directory, manifest, cancelled=lambda: False):
        manifest["proposal_sha256"] = content_digest({k: v for k, v in manifest.items() if k != "proposal_sha256"})
        write_report(directory / "proposals-v1.json", manifest)
        load_proposal_set(directory, cancelled=cancelled)
        if cancelled():
            raise InterruptedError("Recognition cancelled before publication")
        # OS-owned lock prevents concurrent publishers racing the existence
        # check, including an empty destination directory on POSIX. It is
        # released on process death; the bookkeeping file is not a proposal.
        descriptor = os.open(self.root / ".publication.lock", os.O_RDWR | os.O_CREAT, 0o600)
        locked = False
        try:
            if os.name == "nt":
                import msvcrt
                if os.fstat(descriptor).st_size == 0:
                    os.write(descriptor, b"0")
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
            if cancelled():
                raise InterruptedError("Recognition cancelled before publication")
            destination = self.root / manifest["cache_key"]
            if destination.exists():
                return self.get(manifest["cache_key"], cancelled)
            os.rename(directory, destination)
        finally:
            if locked:
                if os.name == "nt":
                    os.lseek(descriptor, 0, os.SEEK_SET)
                    msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
            os.close(descriptor)
        return destination, load_proposal_set(destination, cancelled=cancelled)
