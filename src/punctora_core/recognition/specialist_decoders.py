"""Branch-specific native-score decoding without probability claims."""
import numpy as np

from .specialist_frames import plan_pixel_centres_world, section_box_world


def sigmoid(values):
    values = np.asarray(values, dtype=np.float64)
    return np.exp(-np.logaddexp(0., -values))


def row_softmax(values):
    values = np.asarray(values, dtype=np.float64)
    shifted = values - values.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.maximum(exp.sum(axis=-1, keepdims=True), np.finfo(np.float64).tiny)


def decode_normalized_boxes(boxes, width, height):
    boxes = np.asarray(boxes, dtype=np.float64)
    if boxes.ndim != 2 or boxes.shape[1] != 4 or not np.isfinite(boxes).all():
        raise ValueError("Detector boxes must be finite N x 4 normalized cx/cy/w/h")
    centre, half = boxes[:, :2], boxes[:, 2:] / 2
    values = np.concatenate((centre - half, centre + half), axis=1)
    return np.clip(values * np.array([width, height, width, height], dtype=np.float64),
                   0., np.array([width - 1, height - 1, width - 1, height - 1], dtype=np.float64))


def decode_section(branch, outputs, frame, threshold=.4):
    boxes = np.asarray(outputs["dets"], dtype=np.float32)
    logits = np.asarray(outputs["labels"], dtype=np.float32)
    if boxes.shape != (1, 300, 4) or logits.shape != (1, 300, 2 if branch == "B" else 1):
        raise ValueError(f"Malformed specialist section outputs for branch {branch}")
    if not np.isfinite(boxes).all() or not np.isfinite(logits).all():
        raise ValueError("Specialist section output is nonfinite")
    if branch == "B":
        native = row_softmax(logits[0])
        scores, classes = native.max(axis=1), native.argmax(axis=1)
        score_kind = "row_softmax_winner_not_calibrated_correctness"
    else:
        scores = sigmoid(logits[0, :, 0])
        classes = np.ones(300, dtype=np.int64)
        score_kind = "sigmoid_query_score_not_calibrated_correctness"
    restored = decode_normalized_boxes(boxes[0], frame.native_width, frame.native_height)
    result = []
    for query in np.flatnonzero(scores >= threshold):
        world = section_box_world(frame, restored[query])
        result.append({"branch": branch, "query_id": int(query), "native_class_id": int(classes[query]),
                       "native_score": float(scores[query]), "native_score_kind": score_kind,
                       "box_native_xyxy": restored[query].tolist(), "world": world,
                       "frame_id": frame.frame_id, "status": "proposed"})
    return result


def decode_masks(branch, outputs):
    logits = np.asarray(outputs["logits"], dtype=np.float32)
    classes = 3 if branch in {"D", "E"} else 2
    if logits.ndim != 4 or logits.shape[0] != 1 or logits.shape[1] != classes or not np.isfinite(logits).all():
        raise ValueError(f"Malformed specialist mask output for branch {branch}")
    labels = logits.argmax(axis=1)[0].astype(np.uint8)
    winning = np.take_along_axis(logits[0], labels[None], axis=0)[0].astype(np.float32)
    ordered = np.partition(logits[0], -2, axis=0)
    margin = (ordered[-1] - ordered[-2]).astype(np.float32)
    return labels, winning, margin


def decode_obb(outputs, frame, threshold=.25, maximum=300):
    boxes = np.asarray(outputs["dets"], dtype=np.float32)
    logits = np.asarray(outputs["labels"], dtype=np.float32)
    angles = np.asarray(outputs["angles"], dtype=np.float32)
    if (boxes.shape != (1, 300, 4) or logits.shape != (1, 300, 3) or angles.shape != (1, 300, 1)
            or not all(np.isfinite(value).all() for value in (boxes, logits, angles))):
        raise ValueError("Malformed specialist oriented-box output")
    scores = sigmoid(logits[0])
    flat = np.argsort(scores.ravel(), kind="stable")[-maximum:][::-1]
    candidates = []
    for flattened in flat:
        query, native_class = divmod(int(flattened), scores.shape[1])
        score = float(scores[query, native_class])
        if score <= threshold:
            continue
        cx, cy, width, height = boxes[0, query]
        angle = float(angles[0, query, 0])
        centre = np.array([cx * frame.model_pixels, cy * frame.model_pixels], dtype=np.float64)
        half = np.array([width * frame.model_pixels, height * frame.model_pixels], dtype=np.float64) / 2
        local = np.array([[-half[0], -half[1]], [half[0], -half[1]],
                          [half[0], half[1]], [-half[0], half[1]]])
        rotation = np.array([[np.cos(angle), -np.sin(angle)], [np.sin(angle), np.cos(angle)]])
        pixel = local @ rotation.T + centre
        world = plan_pixel_centres_world(frame, pixel[:, 1], pixel[:, 0], pixels=frame.model_pixels)
        candidates.append({"branch": "J", "query_id": query, "native_class_id": native_class,
                           "native_score": score, "native_score_kind": "sigmoid_query_class_not_probability",
                           "native_class_scores": scores[query].tolist(),
                           "angle_radians": angle, "corners_xy_m": world.tolist(),
                           "frame_id": frame.frame_id, "status": "proposed"})
    # A query's class alternatives are not independent wall observations.
    by_query = {}
    for candidate in candidates:
        previous = by_query.get(candidate["query_id"])
        if previous is None or candidate["native_score"] > previous["native_score"]:
            by_query[candidate["query_id"]] = candidate
    return [by_query[key] for key in sorted(by_query)]
