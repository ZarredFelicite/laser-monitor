"""Lightweight drift-tolerant indicator localization and state tracking."""

from collections import Counter, deque
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

import cv2
import numpy as np


BBox = Tuple[int, int, int, int]


@dataclass
class LocalizationResult:
    boxes: List[BBox]
    valid: List[bool]
    scores: List[float]
    shift: Tuple[float, float]
    global_response: float
    source: str


@dataclass
class LightObservation:
    class_name: str
    laser_status: str
    confidence: float
    known: bool
    extras: Dict[str, Any] = field(default_factory=dict)


class DriftLocalizer:
    """Locate configured ROIs using bounded global and local translation."""

    def __init__(
        self,
        reference: np.ndarray,
        normalized_boxes: Sequence[Sequence[float]],
        max_total_shift: float = 50.0,
        max_step_shift: float = 8.0,
        min_global_response: float = 0.04,
        min_local_score: float = 0.20,
        local_search_margin: int = 4,
        smoothing: float = 0.75,
        max_hold_frames: int = 2,
    ):
        if reference is None or reference.size == 0:
            raise ValueError("A non-empty reference image is required")
        self.reference = reference.copy()
        self.normalized_boxes = [list(box) for box in normalized_boxes]
        self.max_total_shift = float(max_total_shift)
        self.max_step_shift = float(max_step_shift)
        self.min_global_response = float(min_global_response)
        self.min_local_score = float(min_local_score)
        self.local_search_margin = int(local_search_margin)
        self.smoothing = float(smoothing)
        self.max_hold_frames = int(max_hold_frames)
        self._last_shift: Optional[np.ndarray] = None
        self._hold_count = 0
        self._frame_shape: Optional[Tuple[int, int]] = None
        self._reference_scaled: Optional[np.ndarray] = None
        self._reference_registration: Optional[np.ndarray] = None
        self._hanning: Optional[np.ndarray] = None

    @staticmethod
    def _registration_image(image: np.ndarray, size: Tuple[int, int]) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        resized = cv2.resize(gray, size, interpolation=cv2.INTER_AREA)
        equalized = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(resized)
        gx = cv2.Sobel(equalized, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(equalized, cv2.CV_32F, 0, 1, ksize=3)
        magnitude = cv2.magnitude(gx, gy)
        magnitude -= float(np.mean(magnitude))
        return magnitude

    @staticmethod
    def _structural_image(image: np.ndarray) -> np.ndarray:
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (3, 3), 0)
        gx = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
        gy = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
        return cv2.magnitude(gx, gy)

    @staticmethod
    def _pixel_boxes(
        normalized_boxes: Sequence[Sequence[float]], width: int, height: int
    ) -> List[BBox]:
        boxes = []
        for box in normalized_boxes:
            x1, y1, x2, y2 = [
                int(value * dimension)
                for value, dimension in zip(box, (width, height, width, height))
            ]
            boxes.append((x1, y1, x2, y2))
        return boxes

    def _prepare(self, frame: np.ndarray) -> None:
        height, width = frame.shape[:2]
        if self._frame_shape == (height, width):
            return
        self._frame_shape = (height, width)
        self._reference_scaled = cv2.resize(
            self.reference, (width, height), interpolation=cv2.INTER_AREA
        )
        registration_width = min(480, width)
        registration_height = max(64, int(round(height * registration_width / width)))
        registration_size = (registration_width, registration_height)
        self._reference_registration = self._registration_image(
            self._reference_scaled, registration_size
        )
        self._hanning = cv2.createHanningWindow(registration_size, cv2.CV_32F)
        self._last_shift = None
        self._hold_count = 0

    @staticmethod
    def _clamp_box(box: BBox, width: int, height: int) -> BBox:
        x1, y1, x2, y2 = box
        box_width = max(1, x2 - x1)
        box_height = max(1, y2 - y1)
        x1 = min(max(0, x1), max(0, width - box_width))
        y1 = min(max(0, y1), max(0, height - box_height))
        return x1, y1, min(width, x1 + box_width), min(height, y1 + box_height)

    def _estimate_global_shift(self, frame: np.ndarray) -> Tuple[np.ndarray, float]:
        assert self._reference_registration is not None
        assert self._hanning is not None
        reg_height, reg_width = self._reference_registration.shape
        current = self._registration_image(frame, (reg_width, reg_height))
        (shift_x, shift_y), response = cv2.phaseCorrelate(
            self._reference_registration, current, self._hanning
        )
        frame_height, frame_width = frame.shape[:2]
        shift = np.array(
            [shift_x * frame_width / reg_width, shift_y * frame_height / reg_height],
            dtype=np.float32,
        )
        return shift, float(response)

    def _refine_box(self, frame: np.ndarray, anchor: BBox, shift: np.ndarray) -> Tuple[BBox, float]:
        assert self._reference_scaled is not None
        height, width = frame.shape[:2]
        x1, y1, x2, y2 = anchor
        box_width, box_height = x2 - x1, y2 - y1
        margin_x = max(8, box_width)
        margin_y = max(8, box_height // 3)
        tx1 = max(0, x1 - margin_x)
        ty1 = max(0, y1 - margin_y)
        tx2 = min(width, x2 + margin_x)
        ty2 = min(height, y2 + margin_y)
        template = self._reference_scaled[ty1:ty2, tx1:tx2]
        template_edges = self._structural_image(template)

        expected_x = int(round(tx1 + float(shift[0])))
        expected_y = int(round(ty1 + float(shift[1])))
        search_margin = self.local_search_margin
        sx1 = max(0, expected_x - search_margin)
        sy1 = max(0, expected_y - search_margin)
        sx2 = min(width, expected_x + template.shape[1] + search_margin)
        sy2 = min(height, expected_y + template.shape[0] + search_margin)
        search = frame[sy1:sy2, sx1:sx2]
        if search.shape[0] < template.shape[0] or search.shape[1] < template.shape[1]:
            shifted = tuple(
                int(round(value + delta))
                for value, delta in zip(anchor, (shift[0], shift[1], shift[0], shift[1]))
            )
            return self._clamp_box(shifted, width, height), 0.0

        result = cv2.matchTemplate(
            self._structural_image(search), template_edges, cv2.TM_CCOEFF_NORMED
        )
        _, score, _, location = cv2.minMaxLoc(result)
        context_x = sx1 + location[0]
        context_y = sy1 + location[1]
        local_dx = context_x - tx1
        local_dy = context_y - ty1
        refined = (x1 + local_dx, y1 + local_dy, x2 + local_dx, y2 + local_dy)
        return self._clamp_box(refined, width, height), float(score)

    def locate(self, frame: np.ndarray) -> LocalizationResult:
        self._prepare(frame)
        height, width = frame.shape[:2]
        anchors = self._pixel_boxes(self.normalized_boxes, width, height)
        proposed, response = self._estimate_global_shift(frame)
        total_ok = float(np.linalg.norm(proposed)) <= self.max_total_shift
        step_ok = (
            self._last_shift is None
            or float(np.linalg.norm(proposed - self._last_shift)) <= self.max_step_shift
        )
        global_ok = response >= self.min_global_response and total_ok and step_ok

        source = "tracked"
        if global_ok:
            if self._last_shift is None:
                accepted = proposed
            else:
                accepted = (
                    self.smoothing * proposed + (1.0 - self.smoothing) * self._last_shift
                )
            self._last_shift = accepted
            self._hold_count = 0
        elif self._last_shift is not None and self._hold_count < self.max_hold_frames:
            accepted = self._last_shift
            self._hold_count += 1
            source = "held"
        else:
            accepted = np.zeros(2, dtype=np.float32)
            source = "anchor"

        boxes: List[BBox] = []
        scores: List[float] = []
        valid: List[bool] = []
        for anchor in anchors:
            box, score = self._refine_box(frame, anchor, accepted)
            boxes.append(box)
            scores.append(score)
            # A strong local structural match is sufficient even when broad
            # phase correlation is confused by a large lighting change. The
            # local search remains tightly bounded around the configured ROI.
            valid.append(
                score >= self.min_local_score
                and float(np.linalg.norm(accepted)) <= self.max_total_shift
            )

        return LocalizationResult(
            boxes=boxes,
            valid=valid,
            scores=scores,
            shift=(float(accepted[0]), float(accepted[1])),
            global_response=response,
            source=source,
        )


class AdaptiveLightClassifier:
    """Classify two stack-light segments against local, per-frame backgrounds."""

    def __init__(
        self,
        threshold_ratios: Sequence[Sequence[float]],
        ambiguity_margin: float = 0.08,
        fallback_thresholds: Sequence[float] = (1.4, 1.4),
    ):
        self.threshold_ratios = [list(pair) for pair in threshold_ratios]
        self.ambiguity_margin = float(ambiguity_margin)
        self.fallback_thresholds = (
            float(fallback_thresholds[0]), float(fallback_thresholds[1])
        )
        self._ring_baselines: Dict[int, float] = {}

    def _thresholds(self, roi_index: int) -> Tuple[float, float]:
        if roi_index < len(self.threshold_ratios):
            pair = self.threshold_ratios[roi_index]
        else:
            pair = self.fallback_thresholds
        return float(pair[0]), float(pair[1])

    @staticmethod
    def _trimmed_mean(values: np.ndarray) -> float:
        if values.size == 0:
            return 0.0
        low, high = np.percentile(values, (10, 90))
        trimmed = values[(values >= low) & (values <= high)]
        return float(np.mean(trimmed if trimmed.size else values))

    @staticmethod
    def _ring_pixels(frame_gray: np.ndarray, box: BBox) -> np.ndarray:
        height, width = frame_gray.shape[:2]
        x1, y1, x2, y2 = box
        box_width, box_height = x2 - x1, y2 - y1
        margin_x = max(5, box_width)
        margin_y = max(5, box_height // 4)
        rx1, ry1 = max(0, x1 - margin_x), max(0, y1 - margin_y)
        rx2, ry2 = min(width, x2 + margin_x), min(height, y2 + margin_y)
        context = frame_gray[ry1:ry2, rx1:rx2]
        mask = np.ones(context.shape, dtype=bool)
        mask[y1 - ry1:y2 - ry1, x1 - rx1:x2 - rx1] = False
        return context[mask]

    @staticmethod
    def _segment_features(segment: np.ndarray, ring_median: float, ring_mad: float) -> Dict[str, float]:
        gray = cv2.cvtColor(segment, cv2.COLOR_BGR2GRAY)
        blue = segment[:, :, 0].astype(np.float32)
        green = segment[:, :, 1].astype(np.float32)
        red = segment[:, :, 2].astype(np.float32)
        return {
            "mean": float(np.mean(gray)),
            "p90": float(np.percentile(gray, 90)),
            "ring_z": float((np.percentile(gray, 90) - ring_median) / (ring_mad + 5.0)),
            "red_dominance": float(np.median(red - np.maximum(green, blue))),
            "warm_dominance": float(np.median(np.minimum(red, green) - blue)),
        }

    def classify(
        self,
        frame: np.ndarray,
        box: BBox,
        roi_index: int,
        localized: bool,
        frame_gray: Optional[np.ndarray] = None,
    ) -> LightObservation:
        x1, y1, x2, y2 = box
        roi = frame[y1:y2, x1:x2]
        if roi.size == 0 or roi.shape[0] < 6 or roi.shape[1] < 3:
            return LightObservation("machine_unknown", "unknown", 0.0, False, {"reason": "invalid_roi"})

        if frame_gray is None:
            frame_gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = frame_gray[y1:y2, x1:x2]
        third = max(1, gray.shape[0] // 3)
        top = roi[:third]
        middle = roi[third:2 * third]
        bottom = gray[2 * third:]
        ring = self._ring_pixels(frame_gray, box)
        ring_median = float(np.median(ring)) if ring.size else float(np.median(bottom))
        ring_mad = float(np.median(np.abs(ring - ring_median))) if ring.size else 0.0
        background = float(np.mean(bottom)) if bottom.size else ring_median
        top_features = self._segment_features(top, ring_median, ring_mad)
        mid_features = self._segment_features(middle, ring_median, ring_mad)
        top_threshold, mid_threshold = self._thresholds(roi_index)
        top_ratio = (top_features["mean"] + 3.0) / (background + 3.0)
        mid_ratio = (mid_features["mean"] + 3.0) / (background + 3.0)
        top_margin = top_ratio / max(top_threshold, 0.01) - 1.0
        mid_margin = mid_ratio / max(mid_threshold, 0.01) - 1.0

        def active(
            ratio: float,
            threshold: float,
            margin: float,
            features: Dict[str, float],
            allow_strong_emission: bool = False,
        ) -> bool:
            chroma = max(features["red_dominance"], features["warm_dominance"])
            # Strong localized amber emission remains trustworthy when
            # daylight raises the unlit bottom segment and depresses ratios.
            # Restrict this fallback to the middle lamp: unlit red lenses can
            # produce similarly strong red highlights in direct daylight.
            if (
                allow_strong_emission
                and features["p90"] >= 190.0
                and features["ring_z"] >= 8.5
                and chroma >= 40.0
            ):
                return True
            if ratio < threshold:
                return False
            if margin >= self.ambiguity_margin:
                return True
            return features["ring_z"] >= 1.5 and chroma >= 10.0

        top_active = active(top_ratio, top_threshold, top_margin, top_features)
        if not top_active:
            # A lit red lamp has both a bright core and strong red dominance;
            # this excludes the dim red-lens highlights seen in daylight.
            top_active = (
                top_features["p90"] >= 180.0
                and top_features["ring_z"] >= 6.0
                and top_features["red_dominance"] >= 60.0
            )
        mid_active = active(
            mid_ratio,
            mid_threshold,
            mid_margin,
            mid_features,
            allow_strong_emission=True,
        )
        if top_active and mid_active:
            class_name, laser_status = "machine_active", "active"
        elif top_active:
            class_name, laser_status = "machine_working_only", "inactive"
        elif mid_active:
            class_name, laser_status = "machine_on_only", "inactive"
        else:
            class_name, laser_status = "machine_off", "inactive"

        global_median = float(np.median(frame_gray))
        clipping = float(np.mean((gray <= 2) | (gray >= 253)))
        image_ok = global_median >= 2.0 and clipping < 0.70
        known = bool(localized and image_ok)
        margins = [abs(top_margin), abs(mid_margin)]
        decision_margin = min(1.0, max(0.0, min(margins) / 0.35))
        confidence = (0.35 + 0.65 * decision_margin) if known else 0.0

        alpha = 0.02
        previous = self._ring_baselines.get(roi_index, ring_median)
        if known and min(margins) >= self.ambiguity_margin:
            self._ring_baselines[roi_index] = (1.0 - alpha) * previous + alpha * ring_median

        extras = {
            "vision_known": known,
            "background_brightness": background,
            "ring_median": ring_median,
            "ring_mad": ring_mad,
            "ring_baseline": self._ring_baselines.get(roi_index, previous),
            "top_ratio": top_ratio,
            "mid_ratio": mid_ratio,
            "top_threshold": top_threshold,
            "mid_threshold": mid_threshold,
            "top_margin": top_margin,
            "mid_margin": mid_margin,
            "top_features": top_features,
            "mid_features": mid_features,
            "clipping_fraction": clipping,
        }
        if not known:
            return LightObservation("machine_unknown", "unknown", 0.0, False, extras)
        return LightObservation(class_name, laser_status, confidence, True, extras)


class TemporalStateTracker:
    """Require repeated cycle-level observations before changing trusted state."""

    def __init__(self, confirmations: int = 2, unknown_hold_cycles: int = 3):
        self.confirmations = max(1, int(confirmations))
        self.unknown_hold_cycles = max(0, int(unknown_hold_cycles))
        self._stable: Dict[str, str] = {}
        self._candidates: Dict[str, deque] = {}
        self._unknown_counts: Counter = Counter()

    def seed(self, machine_id: str, class_name: str) -> None:
        if class_name != "machine_unknown":
            self._stable[machine_id] = class_name
            self._candidates[machine_id] = deque(maxlen=self.confirmations)
            self._unknown_counts[machine_id] = 0

    def update(self, machine_id: str, class_name: str, known: bool) -> Tuple[str, bool, str]:
        stable = self._stable.get(machine_id)
        if not known:
            self._unknown_counts[machine_id] += 1
            if stable is not None and self._unknown_counts[machine_id] <= self.unknown_hold_cycles:
                return stable, True, "held_unknown"
            self._candidates.setdefault(
                machine_id, deque(maxlen=self.confirmations)
            ).clear()
            return "machine_unknown", False, "unknown"

        self._unknown_counts[machine_id] = 0
        if stable is None:
            self._stable[machine_id] = class_name
            self._candidates[machine_id] = deque(maxlen=self.confirmations)
            return class_name, True, "initialized"
        if class_name == stable:
            self._candidates[machine_id].clear()
            return stable, True, "stable"

        candidates = self._candidates.setdefault(
            machine_id, deque(maxlen=self.confirmations)
        )
        candidates.append(class_name)
        if len(candidates) == self.confirmations and len(set(candidates)) == 1:
            self._stable[machine_id] = class_name
            candidates.clear()
            return class_name, True, "transition_confirmed"
        return stable, True, "transition_pending"
