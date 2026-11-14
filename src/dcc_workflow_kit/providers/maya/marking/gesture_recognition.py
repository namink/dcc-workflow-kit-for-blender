# SPDX-License-Identifier: GPL-3.0-or-later
"""Direction of a marking-menu stroke for the Quick Gestures option (add-on preference ``mm_quick_gestures``).

The recognizer separates the recent path heading from displacement relative to
the current menu-level anchor. Curved gestures can follow their latest heading,
while straight gestures retain the stability of the anchor vector.
"""
from __future__ import annotations

import math
from collections import deque

SECTORS = ("E", "NE", "N", "NW", "W", "SW", "S", "SE")


def sector_from_vector(dx: float, dy: float) -> str | None:
    if dx == 0 and dy == 0:
        return None
    angle = math.degrees(math.atan2(dy, dx)) % 360.0
    return SECTORS[int((angle + 22.5) // 45.0) % 8]


def _angle_delta(a: float, b: float) -> float:
    return (a - b + 180.0) % 360.0 - 180.0


class GestureRecognizer:
    """Track one menu level's trajectory and estimate stable direction."""

    def __init__(self, window_seconds=0.16, max_points=56,
                 min_segment_px=1.5, switch_margin_degrees=7.0):
        self.window_seconds = float(window_seconds)
        self.max_points = int(max_points)
        self.min_segment_px = float(min_segment_px)
        self.switch_margin_degrees = float(switch_margin_degrees)
        self.reset((0.0, 0.0), 0.0)

    def reset(self, anchor, timestamp=0.0):
        self.anchor = (float(anchor[0]), float(anchor[1]))
        self.points = deque([(float(timestamp), self.anchor)], maxlen=self.max_points)
        self.angle = None
        self.direction = None
        self.confidence = 0.0
        self.local_weight = 0.0
        # Track a coherent run after a sharp turn independently from the
        # anchor-to-pointer vector. This prevents the first long leg from
        # overpowering a deliberate second leg in fast marking gestures.
        self._segment_angle = None
        self._turn_x = 0.0
        self._turn_y = 0.0
        self._turn_len = 0.0
        self._turn_started = 0.0

    def update(self, x, y, timestamp):
        point = (float(x), float(y))
        timestamp = float(timestamp)
        if self.points and point == self.points[-1][1]:
            return self.direction
        previous_point = self.points[-1][1] if self.points else point
        seg_dx = point[0] - previous_point[0]
        seg_dy = point[1] - previous_point[1]
        seg_len = math.hypot(seg_dx, seg_dy)
        if seg_len >= self.min_segment_px:
            seg_angle = math.degrees(math.atan2(seg_dy, seg_dx)) % 360.0
            if self._segment_angle is None:
                self._turn_x, self._turn_y, self._turn_len = seg_dx, seg_dy, seg_len
                self._turn_started = timestamp
            else:
                segment_change = abs(_angle_delta(seg_angle, self._segment_angle))
                if segment_change >= 35.0:
                    # A sharp turn starts a new directional run immediately.
                    self._turn_x, self._turn_y, self._turn_len = seg_dx, seg_dy, seg_len
                    self._turn_started = timestamp
                else:
                    # Only accumulate segments that continue roughly along
                    # the same new heading; small mouse jitter is tolerated.
                    self._turn_x += seg_dx
                    self._turn_y += seg_dy
                    self._turn_len += seg_len
            self._segment_angle = seg_angle
        self.points.append((timestamp, point))
        cutoff = timestamp - self.window_seconds
        while len(self.points) > 2 and self.points[1][0] < cutoff:
            self.points.popleft()

        # Build a normalized, recency-weighted local heading. Capping each
        # segment's weight prevents one long event gap from dominating the path.
        px = py = total_weight = path_len = 0.0
        # Keep a separate very-recent heading: averaging the whole short window
        # can dilute a sharp N -> E turn with the preceding northbound motion.
        recent_x = recent_y = recent_len = 0.0
        pts = list(self.points)
        for i in range(1, len(pts)):
            (_ta, a), (tb, b) = pts[i - 1], pts[i]
            dx, dy = b[0] - a[0], b[1] - a[1]
            length = math.hypot(dx, dy)
            if length < self.min_segment_px:
                continue
            age = max(0.0, timestamp - tb)
            weight = min(length, 18.0) / (1.0 + age * 2.2)
            px += (dx / length) * weight
            py += (dy / length) * weight
            total_weight += weight
            path_len += length
            if timestamp - tb <= 0.055:
                recent_x += dx
                recent_y += dy
                recent_len += length
        if total_weight > 0.0:
            px /= total_weight
            py /= total_weight

        ax, ay = self.anchor
        adx, ady = point[0] - ax, point[1] - ay
        anchor_len = math.hypot(adx, ady)
        if anchor_len > 1.0:
            axn, ayn = adx / anchor_len, ady / anchor_len
        else:
            axn = ayn = 0.0

        # Intent: displacement is the stable default, but
        # a clearly curved path gets more say from the recent local heading.
        travel = max(anchor_len, path_len)
        base_local = 0.62 * min(1.0, path_len / 24.0)
        if anchor_len > 1.0 and total_weight > 0.0:
            anchor_angle = math.degrees(math.atan2(ayn, axn)) % 360.0
            local_angle = math.degrees(math.atan2(py, px)) % 360.0
            turn = abs(_angle_delta(local_angle, anchor_angle))
            if turn >= 35.0 and path_len >= 12.0:
                base_local = max(base_local, 0.92 * min(1.0, path_len / 24.0))
            elif turn <= 25.0:
                base_local = min(base_local, 0.42 * min(1.0, path_len / 24.0))
        self.local_weight = base_local
        long_weight = 1.0 - base_local
        vx = axn * long_weight + px * base_local
        vy = ayn * long_weight + py * base_local
        magnitude = math.hypot(vx, vy)
        if magnitude < 0.08 or travel < max(4.0, self.min_segment_px * 2):
            self.confidence = 0.0
            return self.direction

        candidate_angle = math.degrees(math.atan2(vy, vx)) % 360.0
        candidate_dir = sector_from_vector(vx, vy)

        # Resolve a clear second leg before the anchor blend. Use an adaptive,
        # short distance gate: a coherent straight turn should not need an
        # artificial extra arc or a long travel distance to become actionable.
        # The resultant/length ratio rejects back-and-forth jitter while still
        # allowing sparse mouse-event streams to confirm a genuine turn.
        turn_resultant = math.hypot(self._turn_x, self._turn_y)
        turn_coherence = turn_resultant / max(self._turn_len, 1e-6)
        turn_gate = max(3.8, self.min_segment_px * 2.4)
        if (self._turn_len >= turn_gate and turn_resultant >= 3.4
                and turn_coherence >= 0.72 and self._segment_angle is not None):
            turn_dir = sector_from_vector(self._turn_x, self._turn_y)
            turn_angle = math.degrees(math.atan2(self._turn_y, self._turn_x)) % 360.0
            if turn_dir is not None:
                # Hold the confirmed leg until a new sharp turn starts another
                # run; otherwise the old anchor blend can pull E back to NE/N.
                candidate_angle = turn_angle
                candidate_dir = turn_dir
                vx, vy = self._turn_x, self._turn_y

        # A deliberate, sufficiently long recent segment can confirm a sharp
        # turn without requiring the user to draw an extra curved detour. This
        # is especially important for straight N -> E marking gestures.
        recent_resultant = math.hypot(recent_x, recent_y)
        if recent_len >= 3.8 and recent_resultant >= 3.2 and recent_resultant / max(recent_len, 1e-6) >= 0.72:
            recent_angle = math.degrees(math.atan2(recent_y, recent_x)) % 360.0
            recent_dir = sector_from_vector(recent_x, recent_y)
            if self.angle is not None and recent_dir != self.direction:
                recent_turn = abs(_angle_delta(recent_angle, self.angle))
                if recent_turn >= 40.0:
                    candidate_angle = recent_angle
                    candidate_dir = recent_dir
                    vx, vy = recent_x, recent_y

        if self.angle is not None and candidate_dir != self.direction:
            # Suppress only boundary chatter; a meaningful curved turn can
            # switch sectors instead of being locked to the original heading.
            old_center = (int((self.angle + 22.5) // 45.0) * 45.0) % 360.0
            boundary_margin = abs(_angle_delta(candidate_angle, old_center))
            angular_change = abs(_angle_delta(candidate_angle, self.angle))
            if (boundary_margin < 22.5 + self.switch_margin_degrees
                    and angular_change < 22.5 + self.switch_margin_degrees):
                candidate_dir = self.direction
                candidate_angle = self.angle

        self.angle = candidate_angle
        self.direction = candidate_dir
        # Confidence follows directional coherence, which is more useful for
        # fast marks than net displacement alone (a valid right-angle turn has
        # a smaller net/path ratio by definition). This remains sector-neutral.
        if path_len > 0.0:
            path_coherence = min(1.0, math.hypot(px, py))
        else:
            path_coherence = 0.0
        turn_coherence = min(1.0, turn_resultant / max(self._turn_len, 1e-6))
        self.confidence = max(0.0, min(1.0, 0.55 * path_coherence + 0.45 * turn_coherence))
        return self.direction
