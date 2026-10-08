# Selected routines adapted from Cloud2BIM, aux_functions.py.
# Copyright (c) 2025 Václav Nežerka. MIT licence, see third_party/licenses/Cloud2BIM-MIT.txt.
# Upstream revision: cfb10b09ee7a53ac348c65b7e8f0ce8728f9852e.
# Punctora changes: pure imports, no plotting/global configuration; callers validate
# nonzero segments and work on private copies. Other routines are intentionally omitted.
import math
import numpy as np

def distance_point_to_line(point, line_start, line_end):
    """Calculate the distance from a single point to a line defined by two points."""

    line_start = np.array(line_start)
    line_end = np.array(line_end)
    point = np.array(point)

    # Vector from line_start to line_end
    line_vec = line_end - line_start

    # Vector from line_start to the point
    point_vec = point - line_start

    # Calculate the line length and ensure it's not zero for division
    line_length = np.linalg.norm(line_vec)
    if np.isclose(line_length, 0):
        return np.nan

    # Normalize the line vector
    line_vec_normalized = line_vec / line_length

    # Project point_vec onto the line vector (dot product)
    projection_length = np.dot(point_vec, line_vec_normalized)

    # Calculate the closest point on the line to the point
    closest_point = line_start + projection_length * line_vec_normalized

    # Calculate and return the distance from the point to the closest point on the line
    distance = np.linalg.norm(point - closest_point)

    return distance

def distance_points_to_line_np(points, line_start, line_end):
    """Calculate the Euclidean distances from multiple points to a line defined by two points."""
    points = np.asarray(points)
    line_start = np.asarray(line_start)
    line_end = np.asarray(line_end)

    line_vec = line_end - line_start
    line_length = np.linalg.norm(line_vec)

    if np.isclose(line_length, 0):
        return np.full(points.shape[0], np.nan)

    line_vec_normalized = line_vec / line_length
    point_vecs = points - line_start
    projections = np.dot(point_vecs, line_vec_normalized)

    on_segment = (projections >= 0) & (projections <= line_length)
    closest_points = np.outer(projections, line_vec_normalized) + line_start
    perpendicular_distances = np.linalg.norm(points - closest_points, axis=1)

    distances_to_start = np.linalg.norm(points - line_start, axis=1)
    distances_to_end = np.linalg.norm(points - line_end, axis=1)
    distances = np.where(on_segment, perpendicular_distances, np.minimum(distances_to_start, distances_to_end))

    return distances

def distance_between_points(point1, point2):
    """Calculate the Euclidean distance between two points."""
    point1 = np.array(point1)
    point2 = np.array(point2)
    return np.linalg.norm(point1 - point2)

def segments_collinearity_check(seg1, seg2, min_thickness, max_distance):
    """Check if two segments are candidates for merging."""
    # Check if the segments are close enough to merge based on maximum wall thickness
    close_enough = any(
        distance_between_points(p1, p2) <= max_distance for p1 in seg1 for p2 in seg2
    )

    # Check if the segments are co-linear
    collinear = any(
        distance_point_to_line(point, seg1[0], seg1[1]) < (min_thickness / 2) for point in seg2
    )

    return close_enough and collinear

def find_furthest_points(all_points):
    def distance(point1, point2):
        return math.sqrt((point2[0] - point1[0]) ** 2 + (point2[1] - point1[1]) ** 2)

    max_distance = -1
    start_point = None
    end_point = None

    # Iterate through each pair of points to find the furthest pair
    for i in range(len(all_points)):
        for j in range(i + 1, len(all_points)):
            dist = distance(all_points[i], all_points[j])
            if dist > max_distance:
                max_distance = dist
                start_point = all_points[i]
                end_point = all_points[j]

    return start_point, end_point

def merge_collinear_segments(segments, min_thickness, max_distance):
    """Merge co-linear segments from the given list using the direct approach we tested."""
    final_segments = []
    counter = 0
    while segments:
        counter += 1
        base_segment = segments[0]
        to_merge = [base_segment]

        for other_segment in segments[1:]:
            if (segments_collinearity_check(base_segment, other_segment, min_thickness, max_distance)
                    and segments_angle(base_segment, other_segment, angle_tolerance=3)):
                to_merge.append(other_segment)

        # Merge all the segments in to_merge into a single segment
        if len(to_merge) > 1:
            all_points = [point for seg in to_merge for point in seg]
            start, end = find_furthest_points(all_points)
            merged_segment = [start, end]
            segments.append(merged_segment)
        else:
            final_segments.append(base_segment)

        for seg in to_merge:
            segments.remove(seg)

    return final_segments

def angle_between_segments(seg1, seg2):
    """Calculate the angle (in degrees) between two segments."""
    dx1 = seg1[1][0] - seg1[0][0]
    dy1 = seg1[1][1] - seg1[0][1]
    dx2 = seg2[1][0] - seg2[0][0]
    dy2 = seg2[1][1] - seg2[0][1]

    dot_product = dx1 * dx2 + dy1 * dy2
    magnitude1 = (dx1 ** 2 + dy1 ** 2) ** 0.5
    magnitude2 = (dx2 ** 2 + dy2 ** 2) ** 0.5

    if magnitude1 * magnitude2 == 0:
        return 90  # Perpendicular

    cosine_angle = dot_product / (magnitude1 * magnitude2)
    angle_rad = math.acos(min(1, max(-1, cosine_angle)))  # Clip to avoid out of domain error
    angle_deg = math.degrees(angle_rad)

    return angle_deg

def segments_angle(seg1, seg2, angle_tolerance=3):
    """Check if two segments are approximately parallel within a given angle tolerance (in degrees)."""
    angle = angle_between_segments(seg1, seg2)
    return abs(angle) < angle_tolerance or abs(angle - 180) < angle_tolerance

def check_overlap_parallel_segments(seg1, seg2, min_overlap):
    def calculate_angle(p1, p2):
        dx = p2[0] - p1[0]
        dy = p2[1] - p1[1]
        return math.atan2(dy, dx)

    def rotate_point(point, angle_for_rotation):
        rotation_matrix = np.array([
            [np.cos(angle_for_rotation), -np.sin(angle_for_rotation)],
            [np.sin(angle_for_rotation), np.cos(angle_for_rotation)]
        ])
        return np.dot(rotation_matrix, np.array([point[0], point[1]]))

    def process_and_rotate_segments(seg_1, seg_2, rot_angle):
        return [
            [rotate_point(seg_1[0], -rot_angle), rotate_point(seg_1[1], -rot_angle)],
            [rotate_point(seg_2[0], -rot_angle), rotate_point(seg_2[1], -rot_angle)]
        ]

    def find_x_axis_overlap(rot_seg1, rot_seg2):
        x1_min, x1_max = sorted([rot_seg1[0][0], rot_seg1[1][0]])
        x2_min, x2_max = sorted([rot_seg2[0][0], rot_seg2[1][0]])
        start = max(x1_min, x2_min)
        end = min(x1_max, x2_max)
        return (start, end) if start < end else None

    def calculate_overlap_length(overlay):
        return overlay[1] - overlay[0] if overlay else 0

    # Calculate the rotation angle for the first segment to align with the x-axis
    angle = calculate_angle(seg1[0], seg1[1])

    # Rotate both segments using the calculated angle
    rotated_seg1, rotated_seg2 = process_and_rotate_segments(seg1, seg2, angle)

    # Find overlap along the x-axis
    overlap = find_x_axis_overlap(rotated_seg1, rotated_seg2)
    overlap_length = calculate_overlap_length(overlap)

    # Check if the overlap length meets the minimum requirement
    return overlap_length > min_overlap

def line_intersection(line1, line2):
    """Find the intersection point of two lines (if it exists)."""
    xdiff = (line1[0][0] - line1[1][0], line2[0][0] - line2[1][0])
    ydiff = (line1[0][1] - line1[1][1], line2[0][1] - line2[1][1])

    def det(a, b):
        return a[0] * b[1] - a[1] * b[0]

    div = det(xdiff, ydiff)
    if div == 0:
        return None  # Lines don't intersect

    d = (det(*line1), det(*line2))
    x = det(d, xdiff) / div
    y = det(d, ydiff) / div
    return x, y

def adjust_intersections(wall_axes, max_wall_thickness):
    """Adjust wall axes to account for intersections."""
    half_max_thickness = max_wall_thickness / 2

    for i, axis1 in enumerate(wall_axes):
        for j, axis2 in enumerate(wall_axes):
            if i == j:
                continue  # Don't compare the segment with itself

            intersection = line_intersection(axis1, axis2)
            if intersection:
                # Check the distance from the intersection to each endpoint of the axes
                for k in range(2):  # Check both endpoints for each axis
                    if distance_between_points(axis1[k], intersection) <= half_max_thickness:
                        axis1[k] = list(intersection)
                    if distance_between_points(axis2[k], intersection) <= half_max_thickness:
                        axis2[k] = list(intersection)

    return wall_axes
