"""Review-only recognition lifecycle and bounded, order-independent fusion."""
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
import numpy as np

from ..storage import mapped_array
from .contracts import TAXONOMY, validate_labels


def implementation_fingerprint():
    """Invalidate caches when core/adapter code changes without a release bump."""
    import hashlib
    digest = hashlib.sha256()
    root = Path(__file__).resolve().parents[1]
    for path in sorted(root.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


@dataclass
class TilePrediction:
    labels: np.ndarray
    scores: np.ndarray


class RecognitionProvider(ABC):
    """Providers never receive benchmark truth, accept geometry or write IFC."""
    instances = ()
    warnings = ()

    @abstractmethod
    def descriptor(self):
        """All runtime/model/preprocessing settings affecting predictions."""

    @abstractmethod
    def prepare(self, cloud, identity, directory, control):
        """Acquire explicit assets or raise ProviderUnavailable."""

    @abstractmethod
    def infer_chunk(self, tile, directory, control):
        """One int16 label and finite float32 native score per context row."""

    def combine_tiles(self, shards, count, directory, control):
        return combine_tiles(shards, count, directory, control)

    def close(self):
        pass


def write_vote_shard(tile, prediction, directory):
    validate_labels(prediction.labels, prediction.scores, len(tile.points))
    selected = tile.vote_mask & (prediction.labels >= 0)
    rows = tile.context_rows[selected]
    order = np.argsort(rows, kind="stable")
    values = np.empty(len(rows), dtype=[("row", "<u8"), ("label", "<i2"), ("score", "<f4")])
    values["row"], values["label"], values["score"] = rows[order], prediction.labels[selected][order], prediction.scores[selected][order]
    path = Path(directory) / ("votes-" + tile.id.replace(":", "_") + ".npy")
    np.save(path, values, allow_pickle=False)
    return path


def combine_tiles(shards, count, directory, control):
    """Bounded per-row voting, no cloud-sized N x taxonomy allocation.

    Count is the authority. Native scores are *not* calibrated probabilities
    and do not break ties. A winning score is the maximum native score from
    votes for that winning class. Shard order cannot affect the result.
    """
    outputs, maps = [], []
    try:
        labels = mapped_array(Path(directory) / "labels.npy", "<i2", (count,))
        outputs.append(labels)
        scores = mapped_array(Path(directory) / "scores.npy", "<f4", (count,))
        outputs.append(scores)
        for shard in shards:
            maps.append(np.load(shard, mmap_mode="r", allow_pickle=False))
        for begin in range(0, count, control.chunk_points):
            control.check()
            end = min(count, begin + control.chunk_points)
            votes = np.zeros((end - begin, len(TAXONOMY)), dtype=np.uint32)
            native = np.full(votes.shape, -np.inf, dtype=np.float32)
            for values in maps:
                left, right = np.searchsorted(values["row"], [begin, end])
                part = values[left:right]
                row, label = part["row"].astype(np.int64) - begin, part["label"]
                np.add.at(votes, (row, label), 1)
                np.maximum.at(native, (row, label), part["score"])
            winner = votes.argmax(axis=1).astype("<i2")
            known = votes[np.arange(len(winner)), winner] > 0
            labels[begin:end] = np.where(known, winner, -1)
            scores[begin:end] = np.where(known, native[np.arange(len(winner)), winner], 0.)
        for value in outputs:
            value.flush()
    finally:
        for value in [*maps, *outputs]:
            value._mmap.close()
    return {"labels": "labels.npy", "scores": "scores.npy"}
