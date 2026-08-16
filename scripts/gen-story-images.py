#!/usr/bin/env python3
# Install dependencies:
# python3 -m venv scripts/.venv && scripts/.venv/bin/python -m pip install Pillow==12.3.0 numpy==2.5.2

"""Procedural editorial story image generator for 오늘, 기록.

The rendering pipeline is intentionally old-camera rather than clean:
large color fields, soft bloom, a blur pass, crisp monochrome grain,
off-center vignetting, and a small expired-film channel cast. Each story
has its own seed, so rerunning the script reproduces the same JPEG bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import tempfile
import unittest
from pathlib import Path
from typing import Any


class GeneratorTests(unittest.TestCase):
    def test_generate_all_writes_three_deterministic_story_images(self) -> None:
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_dir = Path(first)
            second_dir = Path(second)

            generate_all(first_dir)
            generate_all(second_dir)

            first_files = sorted(first_dir.glob("*.jpg"))
            second_files = sorted(second_dir.glob("*.jpg"))
            self.assertEqual(sorted(story["slug"] + ".jpg" for story in STORIES), [p.name for p in first_files])
            self.assertEqual([p.name for p in first_files], [p.name for p in second_files])

            for first_file, second_file in zip(first_files, second_files):
                self.assertLessEqual(first_file.stat().st_size, TARGET_BYTES)
                self.assertEqual(_sha256(first_file), _sha256(second_file))

    def test_rendered_images_have_expected_dimensions_and_visible_grain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            generate_all(out_dir)

            from PIL import Image
            from PIL import ImageFilter
            import numpy as np

            for image_path in out_dir.glob("*.jpg"):
                with Image.open(image_path) as image:
                    self.assertEqual(image.size, (1600, 1000))
                    pixels = np.asarray(image.convert("L"), dtype=np.float32)
                    residual = pixels - np.asarray(
                        image.convert("L").filter(ImageFilter.GaussianBlur(1.4)), dtype=np.float32
                    )
                    self.assertGreater(float(residual.std()), 2.0)

    def test_scene_primitives_create_geometry_shadows_and_depth_blur(self) -> None:
        from PIL import Image
        import numpy as np

        canvas = Image.new("RGB", (240, 160), "#F0EBE0")
        quad = [(22, 38), (184, 18), (222, 88), (42, 126)]
        quad_mask = perspective_quad_mask(canvas.size, quad)
        filled = fill_perspective_quad(canvas, quad, "#FAF8F3", opacity=0.92)
        object_mask = silhouette_mask(canvas.size, "ellipse", (68, 56, 116, 102))
        shadowed = cast_directional_shadow(filled, object_mask, offset=(42, 28), skew=0.18, blur=6, opacity=0.55)
        focused = depth_varying_blur(shadowed, middle_y=0.50, sharp_band=0.30, mid_radius=1.0, edge_radius=10.0)

        quad_pixels = np.asarray(quad_mask, dtype=np.uint8)
        before = np.asarray(canvas, dtype=np.int16)
        after_shadow = np.asarray(shadowed, dtype=np.int16)
        after_focus = np.asarray(focused.convert("L"), dtype=np.float32)

        self.assertGreater(int(quad_pixels.sum()), 900_000)
        self.assertGreater(int(np.abs(np.asarray(filled, dtype=np.int16) - before).sum()), 100_000)
        self.assertLess(float(after_shadow[118:145, 122:184].mean()), float(np.asarray(filled)[118:145, 122:184].mean()))
        middle_edge = np.abs(np.diff(after_focus[60:100], axis=1)).mean()
        top_edge = np.abs(np.diff(after_focus[:28], axis=1)).mean()
        self.assertGreater(float(middle_edge), float(top_edge) * 1.25)

    def test_story_outputs_have_distinct_scene_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            generate_all(out_dir)

            one = _structure_metrics(out_dir / "one-photo-one-line.jpg")
            where = _structure_metrics(out_dir / "where-your-diary-lives.jpg")
            no = _structure_metrics(out_dir / "no-streak-no-guilt.jpg")

            self.assertGreater(one["edge_structure"], no["edge_structure"] + 0.8)
            self.assertGreater(one["std"], 38.0)
            self.assertLess(where["mean"], 125.0)
            self.assertGreater(where["lower_cluster_minus_corners"], 28.0)
            self.assertGreater(where["edge_structure"], no["edge_structure"] + 1.5)
            self.assertLess(no["std"], 24.0)
            self.assertGreater(no["horizon_gradient"], 0.16)

    def test_no_streak_horizon_has_readable_minimal_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out_dir = Path(tmp)
            story = next(story for story in STORIES if story["slug"] == "no-streak-no-guilt")
            save_jpeg(render_story(story), out_dir / "no-streak-no-guilt.jpg")

            metrics = _horizon_scene_metrics(out_dir / "no-streak-no-guilt.jpg")
            self.assertGreater(metrics["sun_lift"], 3.0)
            self.assertGreater(metrics["sky_band_std"], 2.0)
            self.assertGreater(metrics["sky_minus_ground"], 26.0)
            self.assertGreater(metrics["horizon_mean_y"], 635.0)
            self.assertGreater(metrics["horizon_y_range"], 24.0)
            self.assertGreater(metrics["vignette_drop"], 31.0)
            self.assertGreater(metrics["std"], 14.0)
            self.assertLess(metrics["std"], 30.0)


WIDTH = 1600
HEIGHT = 1000
JPEG_QUALITY = 82
TARGET_BYTES = 250_000

PALETTE = {
    "paper": "#FAF8F3",
    "cream": "#F5F2EA",
    "warm": "#F0EBE0",
    "accent": "#C4956A",
    "dark": "#2C2826",
    "muted": "#7A7068",
    "cool_muted": "#676D70",
    "deep_cool": "#3B4144",
}

STORIES: list[dict[str, Any]] = [
    {
        "slug": "one-photo-one-line",
        "scene": "window_table",
        "seed": 2024081601,
        "base": "#E6DACB",
        "points": [
            {"color": "#FAF8F3", "center": (0.18, 0.12), "radius": 0.48, "strength": 0.86},
            {"color": "#C4956A", "center": (0.30, 0.36), "radius": 0.74, "strength": 0.42},
            {"color": "#7A7068", "center": (1.06, 0.96), "radius": 0.82, "strength": 0.40},
            {"color": "#F5F2EA", "center": (0.66, 0.50), "radius": 1.10, "strength": 0.18},
        ],
        "linears": [
            {"color": "#FAF8F3", "angle": 34.0, "offset": -0.30, "width": 0.46, "strength": 0.35},
            {"color": "#C4956A", "angle": 116.0, "offset": 0.42, "width": 0.52, "strength": 0.21},
            {"color": "#2C2826", "angle": -38.0, "offset": 0.67, "width": 0.70, "strength": 0.15},
        ],
        "blooms": [
            {
                "center": (0.20, 0.15),
                "radius": (0.26, 0.18),
                "halo_radius": (0.56, 0.39),
                "color": "#FAF8F3",
                "halo": "#C4956A",
                "strength": 0.76,
                "halo_strength": 0.38,
                "lift": 0.18,
            },
            {
                "center": (0.42, 0.42),
                "radius": (0.34, 0.10),
                "halo_radius": (0.56, 0.24),
                "color": "#F5F2EA",
                "halo": "#C4956A",
                "strength": 0.13,
                "halo_strength": 0.16,
                "lift": 0.04,
            },
        ],
        "blur": 26,
        "focus": {"middle_y": 0.56, "sharp_band": 0.24, "mid_radius": 2.0, "edge_radius": 15.0},
        "grain": 0.057,
        "vignette": {"center": (0.42, 0.37), "amount": 0.38, "power": 1.74},
        "cast": {"shadow_amber": 0.040, "shadow_green": 0.024, "blue_lift": -0.018, "desaturate": 0.08},
        "leak": None,
    },
    {
        "slug": "where-your-diary-lives",
        "scene": "drawer_stack",
        "seed": 2024081602,
        "base": "#676D70",
        "points": [
            {"color": "#2C2826", "center": (0.18, 0.76), "radius": 0.98, "strength": 0.50},
            {"color": "#3B4144", "center": (0.44, 0.55), "radius": 0.92, "strength": 0.42},
            {"color": "#7A7068", "center": (0.78, 0.38), "radius": 0.76, "strength": 0.24},
            {"color": "#C4956A", "center": (1.04, 0.42), "radius": 0.44, "strength": 0.42},
        ],
        "linears": [
            {"color": "#2C2826", "angle": 8.0, "offset": -0.52, "width": 0.75, "strength": 0.20},
            {"color": "#C4956A", "angle": 0.0, "offset": 0.74, "width": 0.24, "strength": 0.20},
        ],
        "blooms": [
            {
                "center": (0.88, 0.38),
                "radius": (0.18, 0.25),
                "halo_radius": (0.38, 0.47),
                "color": "#F0EBE0",
                "halo": "#C4956A",
                "strength": 0.31,
                "halo_strength": 0.26,
                "lift": 0.07,
            }
        ],
        "blur": 26,
        "focus": {"middle_y": 0.62, "sharp_band": 0.28, "mid_radius": 2.5, "edge_radius": 17.0},
        "grain": 0.065,
        "vignette": {"center": (0.57, 0.48), "amount": 0.42, "power": 1.66},
        "cast": {"shadow_amber": 0.014, "shadow_green": 0.036, "blue_lift": 0.026, "desaturate": 0.16},
        "leak": {"edge": "right", "color": "#C4956A", "strength": 0.15, "width": 0.12},
    },
    {
        "slug": "no-streak-no-guilt",
        "scene": "overcast_horizon",
        "seed": 2024081603,
        "base": "#F5F2EA",
        "points": [
            {"color": "#FAF8F3", "center": (0.38, 0.24), "radius": 0.74, "strength": 0.64},
            {"color": "#F0EBE0", "center": (0.82, 0.76), "radius": 0.86, "strength": 0.23},
            {"color": "#D8D2C7", "center": (-0.08, 0.88), "radius": 0.68, "strength": 0.17},
            {"color": "#EEECE8", "center": (0.50, 0.50), "radius": 1.24, "strength": 0.18},
        ],
        "linears": [
            {"color": "#FAF8F3", "angle": -8.0, "offset": -0.26, "width": 0.72, "strength": 0.18},
            {"color": "#E4DED2", "angle": 82.0, "offset": 0.38, "width": 0.82, "strength": 0.10},
        ],
        "blooms": [
            {
                "center": (0.40, 0.30),
                "radius": (0.06, 0.05),
                "halo_radius": (0.18, 0.15),
                "color": "#FAF8F3",
                "halo": "#F0EBE0",
                "strength": 0.58,
                "halo_strength": 0.06,
                "lift": 0.20,
            }
        ],
        "blur": 28,
        "focus": {"middle_y": 0.67, "sharp_band": 0.18, "mid_radius": 2.0, "edge_radius": 13.0},
        "grain": 0.041,
        "vignette": {"center": (0.48, 0.45), "amount": 0.25, "power": 1.54},
        "cast": {"shadow_amber": 0.015, "shadow_green": 0.013, "blue_lift": 0.004, "desaturate": 0.13},
        "leak": None,
    },
]


def hex_to_rgb(value: str) -> "np.ndarray":
    import numpy as np

    stripped = value.lstrip("#")
    return np.array([int(stripped[i : i + 2], 16) for i in (0, 2, 4)], dtype=np.float32) / 255.0


def coordinate_fields(width: int, height: int) -> tuple["np.ndarray", "np.ndarray"]:
    import numpy as np

    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    x = np.linspace(0.0, 1.0, width, dtype=np.float32)[None, :]
    return x, y


def gaussian_field(
    x: "np.ndarray",
    y: "np.ndarray",
    center: tuple[float, float],
    radius: float | tuple[float, float],
    rotation: float = 0.0,
) -> "np.ndarray":
    import numpy as np

    if isinstance(radius, tuple):
        rx, ry = radius
    else:
        rx = ry = radius
    cx, cy = center
    angle = np.deg2rad(rotation)
    cos_a = np.cos(angle)
    sin_a = np.sin(angle)
    dx = x - cx
    dy = y - cy
    xr = dx * cos_a + dy * sin_a
    yr = -dx * sin_a + dy * cos_a
    return np.exp(-0.5 * ((xr / rx) ** 2 + (yr / ry) ** 2)).astype(np.float32)


def blend_toward(image: "np.ndarray", color: "np.ndarray", mask: "np.ndarray") -> "np.ndarray":
    weight = mask[..., None].clip(0.0, 1.0)
    return image * (1.0 - weight) + color * weight


def hex_to_pil(value: str) -> tuple[int, int, int]:
    stripped = value.lstrip("#")
    return tuple(int(stripped[i : i + 2], 16) for i in (0, 2, 4))


def jittered_polygon(
    points: list[tuple[float, float]] | tuple[tuple[float, float], ...],
    rng: "np.random.Generator | None" = None,
    edge_jitter: float = 0.0,
    steps_per_edge: int = 7,
) -> list[tuple[float, float]]:
    if rng is None or edge_jitter <= 0:
        return [(float(x), float(y)) for x, y in points]

    import numpy as np

    result: list[tuple[float, float]] = []
    for index, start in enumerate(points):
        end = points[(index + 1) % len(points)]
        sx, sy = start
        ex, ey = end
        dx = ex - sx
        dy = ey - sy
        length = max((dx * dx + dy * dy) ** 0.5, 1.0)
        nx = -dy / length
        ny = dx / length
        for step in range(steps_per_edge):
            t = step / steps_per_edge
            taper = np.sin(np.pi * t)
            wobble = float(rng.normal(0.0, edge_jitter)) * taper
            result.append((sx + dx * t + nx * wobble, sy + dy * t + ny * wobble))
    return result


def perspective_quad_mask(
    size: tuple[int, int],
    points: list[tuple[float, float]] | tuple[tuple[float, float], ...],
    rng: "np.random.Generator | None" = None,
    edge_jitter: float = 0.0,
) -> "Image.Image":
    from PIL import Image
    from PIL import ImageDraw

    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    draw.polygon(jittered_polygon(points, rng, edge_jitter), fill=255)
    return mask


def paint_mask(
    image: "Image.Image",
    mask: "Image.Image",
    color: str,
    opacity: float = 1.0,
    blur: float = 0.0,
) -> "Image.Image":
    from PIL import Image
    from PIL import ImageFilter

    working_mask = mask.filter(ImageFilter.GaussianBlur(blur)) if blur else mask
    alpha = working_mask.point(lambda value: int(value * max(0.0, min(opacity, 1.0))))
    layer = Image.new("RGB", image.size, hex_to_pil(color))
    return Image.composite(layer, image, alpha)


def fill_perspective_quad(
    image: "Image.Image",
    points: list[tuple[float, float]] | tuple[tuple[float, float], ...],
    color: str,
    opacity: float = 1.0,
    rng: "np.random.Generator | None" = None,
    edge_jitter: float = 0.0,
) -> "Image.Image":
    return paint_mask(image, perspective_quad_mask(image.size, points, rng, edge_jitter), color, opacity)


def silhouette_mask(
    size: tuple[int, int],
    kind: str,
    bbox: tuple[float, float, float, float],
    radius: float | None = None,
    angle: float = 0.0,
) -> "Image.Image":
    from PIL import Image
    from PIL import ImageDraw

    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    if kind == "ellipse":
        draw.ellipse(bbox, fill=255)
    elif kind == "bar":
        draw.rounded_rectangle(bbox, radius=radius or 4, fill=255)
    else:
        draw.rounded_rectangle(bbox, radius=radius or 18, fill=255)

    if angle:
        cx = (bbox[0] + bbox[2]) * 0.5
        cy = (bbox[1] + bbox[3]) * 0.5
        mask = mask.rotate(angle, resample=Image.Resampling.BICUBIC, center=(cx, cy))
    return mask


def combine_masks(*masks: "Image.Image") -> "Image.Image":
    from PIL import ImageChops

    if not masks:
        raise ValueError("at least one mask is required")

    result = masks[0]
    for mask in masks[1:]:
        result = ImageChops.lighter(result, mask)
    return result


def intersect_masks(*masks: "Image.Image") -> "Image.Image":
    from PIL import ImageChops

    if not masks:
        raise ValueError("at least one mask is required")

    result = masks[0]
    for mask in masks[1:]:
        result = ImageChops.multiply(result, mask)
    return result


def cast_directional_shadow(
    image: "Image.Image",
    source_mask: "Image.Image",
    offset: tuple[float, float],
    skew: float,
    blur: float,
    opacity: float,
    color: str = "#2C2826",
) -> "Image.Image":
    from PIL import Image
    from PIL import ImageFilter

    width, height = image.size
    dx, dy = offset
    cy = height * 0.5
    transform = (1.0, -skew, -dx + skew * dy + skew * cy, 0.0, 1.0, -dy)
    shadow_mask = source_mask.transform(
        image.size,
        Image.Transform.AFFINE,
        transform,
        resample=Image.Resampling.BICUBIC,
        fillcolor=0,
    )
    shadow_mask = shadow_mask.filter(ImageFilter.GaussianBlur(blur))
    shadow_mask = shadow_mask.point(lambda value: int(value * max(0.0, min(opacity, 1.0))))
    shadow_layer = Image.new("RGB", (width, height), hex_to_pil(color))
    return Image.composite(shadow_layer, image, shadow_mask)


def depth_varying_blur(
    image: "Image.Image",
    middle_y: float,
    sharp_band: float,
    mid_radius: float,
    edge_radius: float,
) -> "Image.Image":
    import numpy as np
    from PIL import Image
    from PIL import ImageFilter

    mid = np.asarray(image.filter(ImageFilter.GaussianBlur(mid_radius)), dtype=np.float32)
    edge = np.asarray(image.filter(ImageFilter.GaussianBlur(edge_radius)), dtype=np.float32)
    height = image.size[1]
    y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None]
    sharp = np.exp(-0.5 * ((y - middle_y) / sharp_band) ** 2)
    # Keep a real focused band, but never let geometry become perfectly digital.
    sharp = np.clip(sharp * 1.08, 0.0, 1.0)
    blended = edge * (1.0 - sharp[..., None]) + mid * sharp[..., None]
    return Image.fromarray(np.uint8(blended.clip(0.0, 255.0)), mode="RGB")


def rotated_quad(
    center: tuple[float, float],
    width: float,
    height: float,
    angle_degrees: float,
    perspective: float = 0.0,
) -> list[tuple[float, float]]:
    import math

    cx, cy = center
    top_width = width * (1.0 - perspective)
    bottom_width = width * (1.0 + perspective)
    corners = [
        (-top_width * 0.5, -height * 0.5),
        (top_width * 0.5, -height * 0.5),
        (bottom_width * 0.5, height * 0.5),
        (-bottom_width * 0.5, height * 0.5),
    ]
    angle = math.radians(angle_degrees)
    cos_a = math.cos(angle)
    sin_a = math.sin(angle)
    return [(cx + x * cos_a - y * sin_a, cy + x * sin_a + y * cos_a) for x, y in corners]


def draw_edge_highlight(
    image: "Image.Image",
    points: list[tuple[float, float]],
    color: str,
    opacity: float,
    width: int = 5,
) -> "Image.Image":
    from PIL import Image
    from PIL import ImageDraw
    from PIL import ImageFilter

    mask = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(mask)
    draw.line([points[0], points[1], points[2]], fill=255, width=width, joint="curve")
    return paint_mask(image, mask.filter(ImageFilter.GaussianBlur(width * 0.5)), color, opacity)


def wavy_band_mask(
    size: tuple[int, int],
    center_y: float,
    thickness: float,
    amplitude: float,
    frequency: float,
    phase: float,
    rng: "np.random.Generator",
    point_count: int = 30,
) -> "Image.Image":
    import numpy as np
    from PIL import Image
    from PIL import ImageDraw

    width, height = size
    xs = np.linspace(-90, width + 90, point_count)
    wobble = np.sin((xs / width) * np.pi * 2.0 * frequency + phase) * amplitude
    wobble += np.sin((xs / width) * np.pi * 2.0 * (frequency * 0.43) + phase * 0.67) * amplitude * 0.45
    jitter = rng.normal(0.0, amplitude * 0.12, size=point_count)
    mid = center_y + wobble + jitter
    upper = [(float(x), float(np.clip(y - thickness * 0.5, -80, height + 80))) for x, y in zip(xs, mid)]
    lower = [(float(x), float(np.clip(y + thickness * 0.5, -80, height + 80))) for x, y in zip(xs[::-1], mid[::-1])]

    mask = Image.new("L", size, 0)
    ImageDraw.Draw(mask).polygon(upper + lower, fill=255)
    return mask


def wavy_horizon_points(
    size: tuple[int, int],
    base_y: float,
    amplitude: float,
    rng: "np.random.Generator",
    point_count: int = 34,
) -> list[tuple[float, float]]:
    import numpy as np

    width, _ = size
    xs = np.linspace(-90, width + 90, point_count)
    phase = float(rng.uniform(0.0, np.pi * 2.0))
    ys = base_y
    ys += np.sin((xs / width) * np.pi * 2.0 * 1.22 + phase) * amplitude
    ys += np.sin((xs / width) * np.pi * 2.0 * 2.75 + phase * 0.41) * amplitude * 0.32
    ys += rng.normal(0.0, 2.0, size=point_count)
    return [(float(x), float(y)) for x, y in zip(xs, ys)]


def paint_vertical_gradient(
    image: "Image.Image",
    mask: "Image.Image",
    top_color: str,
    bottom_color: str,
    opacity: float,
    blur: float = 0.0,
) -> "Image.Image":
    import numpy as np
    from PIL import Image
    from PIL import ImageFilter

    width, height = image.size
    top = hex_to_rgb(top_color)
    bottom = hex_to_rgb(bottom_color)
    gradient_y = np.linspace(0.0, 1.0, height, dtype=np.float32)[:, None, None]
    gradient = top * (1.0 - gradient_y) + bottom * gradient_y
    gradient = np.repeat(gradient, width, axis=1)

    alpha_mask = mask.filter(ImageFilter.GaussianBlur(blur)) if blur else mask
    alpha = (np.asarray(alpha_mask, dtype=np.float32) / 255.0 * opacity)[..., None]
    base = np.asarray(image, dtype=np.float32) / 255.0
    out = base * (1.0 - alpha) + gradient * alpha
    return Image.fromarray(np.uint8(out.clip(0.0, 1.0) * 255), mode="RGB")


def add_masked_texture(
    image: "Image.Image",
    mask: "Image.Image",
    rng: "np.random.Generator",
    strength: float,
    scale: int,
) -> "Image.Image":
    import numpy as np
    from PIL import Image
    from PIL import ImageFilter

    base = np.asarray(image, dtype=np.float32) / 255.0
    texture = low_frequency_noise(rng, image.size[0], image.size[1], scale=scale, strength=strength)
    alpha = np.asarray(mask.filter(ImageFilter.GaussianBlur(22)), dtype=np.float32) / 255.0
    out = base + texture[..., None] * alpha[..., None]
    return Image.fromarray(np.uint8(out.clip(0.0, 1.0) * 255), mode="RGB")


def make_base_field(story: dict[str, Any], rng: "np.random.Generator") -> "np.ndarray":
    import numpy as np

    x, y = coordinate_fields(WIDTH, HEIGHT)
    image = np.ones((HEIGHT, WIDTH, 3), dtype=np.float32) * hex_to_rgb(story["base"])

    for point in story["points"]:
        jitter = rng.normal(0.0, 0.012, size=2)
        center = (point["center"][0] + float(jitter[0]), point["center"][1] + float(jitter[1]))
        radius = point["radius"] * (1.0 + float(rng.normal(0.0, 0.035)))
        mask = gaussian_field(x, y, center, radius) * point["strength"]
        image = blend_toward(image, hex_to_rgb(point["color"]), mask)

    for linear in story["linears"]:
        angle = np.deg2rad(linear["angle"])
        projection = (x - 0.5) * np.cos(angle) + (y - 0.5) * np.sin(angle)
        mask = np.exp(-0.5 * ((projection - linear["offset"]) / linear["width"]) ** 2).astype(np.float32)
        image = blend_toward(image, hex_to_rgb(linear["color"]), mask * linear["strength"])

    texture = low_frequency_noise(rng, WIDTH, HEIGHT, scale=14, strength=0.028)
    return (image + texture[..., None]).clip(0.0, 1.0)


def low_frequency_noise(
    rng: "np.random.Generator", width: int, height: int, scale: int, strength: float
) -> "np.ndarray":
    import numpy as np
    from PIL import Image
    from PIL import ImageFilter

    small_w = max(4, width // scale)
    small_h = max(4, height // scale)
    noise = rng.normal(0.0, 1.0, size=(small_h, small_w)).astype(np.float32)
    lo = float(noise.min())
    hi = float(noise.max())
    normalized = (noise - lo) / (hi - lo)
    image = Image.fromarray(np.uint8(normalized * 255), mode="L")
    image = image.resize((width, height), Image.Resampling.BICUBIC)
    image = image.filter(ImageFilter.GaussianBlur(radius=scale * 0.55))
    expanded = np.asarray(image, dtype=np.float32) / 255.0
    return (expanded - 0.5) * strength


def add_light_bloom(image: "np.ndarray", story: dict[str, Any], rng: "np.random.Generator") -> "np.ndarray":
    import numpy as np

    x, y = coordinate_fields(WIDTH, HEIGHT)
    out = image.copy()
    for bloom in story["blooms"]:
        rotation = float(rng.normal(0.0, 7.0))
        halo = gaussian_field(x, y, bloom["center"], bloom["halo_radius"], rotation)
        core = gaussian_field(x, y, bloom["center"], bloom["radius"], rotation)
        out = blend_toward(out, hex_to_rgb(bloom["halo"]), halo * bloom["halo_strength"])
        out = blend_toward(out, hex_to_rgb(bloom["color"]), core * bloom["strength"])
        lift = bloom.get("lift", 0.0)
        if lift:
            out = out + hex_to_rgb(bloom["color"]) * (core[..., None] * lift + halo[..., None] * lift * 0.22)
    return out.clip(0.0, 1.0)


def blur_image(image: "np.ndarray", radius: float) -> "np.ndarray":
    import numpy as np
    from PIL import Image
    from PIL import ImageFilter

    pil = Image.fromarray(np.uint8(image.clip(0.0, 1.0) * 255), mode="RGB")
    pil = pil.filter(ImageFilter.GaussianBlur(radius=radius))
    return np.asarray(pil, dtype=np.float32) / 255.0


def add_grain(image: "np.ndarray", rng: "np.random.Generator", amplitude: float) -> "np.ndarray":
    import numpy as np

    grain = rng.normal(0.0, amplitude, size=(HEIGHT, WIDTH, 1)).astype(np.float32)
    fine = rng.normal(0.0, amplitude * 0.22, size=(HEIGHT, WIDTH, 1)).astype(np.float32)
    exposure = np.mean(image, axis=2, keepdims=True)
    shadow_bias = (0.72 - exposure).clip(0.0, 0.6)
    return (image + grain * (0.82 + shadow_bias) + fine).clip(0.0, 1.0)


def add_vignette(image: "np.ndarray", vignette: dict[str, Any]) -> "np.ndarray":
    import numpy as np

    x, y = coordinate_fields(WIDTH, HEIGHT)
    cx, cy = vignette["center"]
    distance = np.sqrt(((x - cx) / 0.92) ** 2 + ((y - cy) / 0.80) ** 2)
    mask = np.clip(distance, 0.0, 1.25) ** vignette["power"]
    factor = 1.0 - mask[..., None] * vignette["amount"]
    return (image * factor).clip(0.0, 1.0)


def apply_color_cast(image: "np.ndarray", cast: dict[str, float]) -> "np.ndarray":
    import numpy as np

    out = image.copy()
    luminance = (out[..., 0] * 0.299 + out[..., 1] * 0.587 + out[..., 2] * 0.114)[..., None]
    shadows = np.clip(1.0 - luminance * 1.45, 0.0, 1.0)
    highlights = np.clip((luminance - 0.68) * 2.2, 0.0, 1.0)

    out[..., 0:1] += shadows * cast["shadow_amber"]
    out[..., 1:2] += shadows * cast["shadow_green"]
    out[..., 2:3] += shadows * cast["blue_lift"]
    out[..., 0:1] += highlights * 0.010
    out[..., 2:3] -= highlights * 0.012

    gray = luminance.repeat(3, axis=2)
    out = gray * cast["desaturate"] + out * (1.0 - cast["desaturate"])
    return out.clip(0.0, 1.0)


def add_light_leak(image: "np.ndarray", leak: dict[str, Any] | None) -> "np.ndarray":
    import numpy as np

    if leak is None:
        return image

    x, y = coordinate_fields(WIDTH, HEIGHT)
    if leak["edge"] == "right":
        edge = 1.0 - x
    elif leak["edge"] == "left":
        edge = x
    elif leak["edge"] == "top":
        edge = y
    else:
        edge = 1.0 - y

    horizontal_band = np.exp(-0.5 * ((y - 0.50) / 0.42) ** 2).astype(np.float32)
    mask = np.exp(-0.5 * (edge / leak["width"]) ** 2).astype(np.float32) * horizontal_band * leak["strength"]
    return blend_toward(image, hex_to_rgb(leak["color"]), mask).clip(0.0, 1.0)


def base_image_for_story(story: dict[str, Any], rng: "np.random.Generator") -> "Image.Image":
    import numpy as np
    from PIL import Image

    field = make_base_field(story, rng)
    return Image.fromarray(np.uint8(field.clip(0.0, 1.0) * 255), mode="RGB")


def compose_window_table(story: dict[str, Any], rng: "np.random.Generator") -> "Image.Image":
    from PIL import ImageFilter

    image = base_image_for_story(story, rng)
    image = fill_perspective_quad(
        image,
        [(-120, 210), (1685, 90), (1765, 1080), (-165, 1035)],
        "#7A7068",
        opacity=0.22,
        rng=rng,
        edge_jitter=5.0,
    )

    sunlight = [(95, 250), (970, 150), (1425, 445), (315, 762)]
    sunlight_mask = perspective_quad_mask(image.size, sunlight, rng, edge_jitter=6.0)
    image = paint_mask(image, sunlight_mask.filter(ImageFilter.GaussianBlur(34)), "#C4956A", opacity=0.26)
    image = paint_mask(image, sunlight_mask, "#FAF8F3", opacity=0.76)

    mullions = [
        [(290, 225), (364, 207), (635, 708), (538, 736)],
        [(682, 183), (755, 198), (1028, 598), (940, 626)],
        [(140, 408), (1290, 480), (1322, 545), (152, 470)],
    ]
    for bar in mullions:
        bar_mask = intersect_masks(perspective_quad_mask(image.size, bar, rng, edge_jitter=3.0), sunlight_mask)
        image = paint_mask(image, bar_mask, "#2C2826", opacity=0.42, blur=1.4)

    cup_body = silhouette_mask(image.size, "rounded_rect", (372, 548, 486, 660), radius=35, angle=-4.0)
    cup_top = silhouette_mask(image.size, "ellipse", (360, 526, 492, 586), angle=-4.0)
    cup_mask = combine_masks(cup_body, cup_top)
    image = cast_directional_shadow(image, cup_mask, offset=(285, 175), skew=0.25, blur=36, opacity=0.42)
    image = paint_mask(image, cup_mask.filter(ImageFilter.GaussianBlur(1.2)), "#2C2826", opacity=0.62)
    image = paint_mask(image, cup_top.filter(ImageFilter.GaussianBlur(3.0)), "#7A7068", opacity=0.24)

    return image


def compose_drawer_stack(story: dict[str, Any], rng: "np.random.Generator") -> "Image.Image":
    from PIL import ImageFilter

    image = base_image_for_story(story, rng)
    image = fill_perspective_quad(
        image,
        [(-80, 280), (1690, 160), (1705, 1040), (-120, 1030)],
        "#2C2826",
        opacity=0.28,
        rng=rng,
        edge_jitter=4.0,
    )
    image = fill_perspective_quad(
        image,
        [(1185, 115), (1655, 70), (1645, 1010), (1260, 1040)],
        "#C4956A",
        opacity=0.10,
        rng=rng,
        edge_jitter=3.0,
    )

    side_bar = silhouette_mask(image.size, "bar", (92, 150, 188, 930), radius=12, angle=-2.0)
    image = cast_directional_shadow(image, side_bar, offset=(-38, 34), skew=-0.10, blur=28, opacity=0.24)
    image = paint_mask(image, side_bar.filter(ImageFilter.GaussianBlur(2.8)), "#2C2826", opacity=0.28)

    prints = [
        ((705, 652), 780, 475, -8.5, "#D8D2C7", 0.60),
        ((790, 612), 805, 465, 4.0, "#F0EBE0", 0.68),
        ((738, 590), 735, 430, -3.0, "#C9C3B8", 0.62),
        ((848, 558), 765, 430, 7.0, "#F5F2EA", 0.72),
        ((800, 530), 690, 382, -1.4, "#E7E0D4", 0.80),
        ((912, 502), 590, 330, 3.8, "#FAF8F3", 0.76),
    ]
    for center, width, height, angle, color, opacity in prints:
        points = rotated_quad(center, width, height, angle, perspective=0.035)
        mask = perspective_quad_mask(image.size, points, rng, edge_jitter=3.0)
        image = cast_directional_shadow(image, mask, offset=(-32, 34), skew=-0.09, blur=18, opacity=0.30)
        image = paint_mask(image, mask, color, opacity=opacity)
        image = draw_edge_highlight(image, points, "#C4956A", opacity=0.18, width=7)
        inset = rotated_quad((center[0] + 5, center[1] - 2), width * 0.86, height * 0.78, angle + 0.4, perspective=0.028)
        image = fill_perspective_quad(image, inset, "#7A7068", opacity=0.055, rng=rng, edge_jitter=2.5)

    return image


def compose_overcast_horizon(story: dict[str, Any], rng: "np.random.Generator") -> "Image.Image":
    from PIL import Image
    from PIL import ImageChops
    from PIL import ImageDraw
    from PIL import ImageFilter

    image = base_image_for_story(story, rng)
    sky = Image.new("L", image.size, 255)
    image = paint_mask(image, sky, "#FAF8F3", opacity=0.38)

    cloud_bands = [
        (185, 110, 18, 0.72, "#E3DED5", 0.18, 40),
        (280, 128, 24, 1.05, "#F5F2EA", 0.24, 52),
        (405, 118, 20, 0.88, "#DDD8CE", 0.18, 46),
        (530, 96, 15, 1.30, "#F0EBE0", 0.16, 36),
    ]
    for center_y, thickness, amplitude, frequency, color, opacity, blur in cloud_bands:
        phase = float(rng.uniform(0.0, 6.28318530718))
        mask = wavy_band_mask(image.size, center_y, thickness, amplitude, frequency, phase, rng)
        image = paint_mask(image, mask.filter(ImageFilter.GaussianBlur(blur)), color, opacity=opacity)

    sun = silhouette_mask(image.size, "ellipse", (548, 218, 734, 396))
    sun_core = silhouette_mask(image.size, "ellipse", (578, 246, 704, 374))
    sun_veil = silhouette_mask(image.size, "ellipse", (468, 172, 816, 452))
    sun_ring = ImageChops.subtract(sun_veil.filter(ImageFilter.GaussianBlur(32)), sun_core.filter(ImageFilter.GaussianBlur(34)))
    image = paint_mask(image, sun.filter(ImageFilter.GaussianBlur(80)), "#F0EBE0", opacity=0.08)
    image = paint_mask(image, sun_ring, "#D8D2C7", opacity=0.62)
    image = paint_mask(image, sun_core.filter(ImageFilter.GaussianBlur(28)), "#FAF8F3", opacity=0.68)
    image = paint_mask(image, sun_core.filter(ImageFilter.GaussianBlur(8)), "#FAF8F3", opacity=0.88)

    horizon_points = wavy_horizon_points(image.size, base_y=674, amplitude=25, rng=rng)
    ground_polygon = horizon_points + [(1690, 1085), (-100, 1085)]
    ground_mask = Image.new("L", image.size, 0)
    ImageDraw.Draw(ground_mask).polygon(ground_polygon, fill=255)
    image = paint_vertical_gradient(image, ground_mask, "#E5DED3", "#CFC7BA", opacity=0.62, blur=1.5)
    image = add_masked_texture(image, ground_mask, rng, strength=0.035, scale=18)

    horizon = Image.new("L", image.size, 0)
    draw = ImageDraw.Draw(horizon)
    draw.line(horizon_points, fill=255, width=7, joint="curve")
    image = paint_mask(image, horizon.filter(ImageFilter.GaussianBlur(7.0)), "#7A7068", opacity=0.16)

    near_ground = wavy_band_mask(image.size, 820, 150, 18, 0.80, float(rng.uniform(0.0, 6.28318530718)), rng)
    image = paint_mask(image, near_ground.filter(ImageFilter.GaussianBlur(64)), "#7A7068", opacity=0.075)

    return image


def compose_scene(story: dict[str, Any], rng: "np.random.Generator") -> "Image.Image":
    if story["scene"] == "window_table":
        return compose_window_table(story, rng)
    if story["scene"] == "drawer_stack":
        return compose_drawer_stack(story, rng)
    if story["scene"] == "overcast_horizon":
        return compose_overcast_horizon(story, rng)
    raise ValueError(f"Unknown story scene: {story['scene']}")


def apply_film_treatment(image: "Image.Image", story: dict[str, Any], rng: "np.random.Generator") -> "Image.Image":
    import numpy as np
    from PIL import Image

    image_array = np.asarray(image, dtype=np.float32) / 255.0
    image_array = add_light_bloom(image_array, story, rng)
    image_array = add_light_leak(image_array, story["leak"])
    bloomed = Image.fromarray(np.uint8(image_array.clip(0.0, 1.0) * 255), mode="RGB")
    focused = depth_varying_blur(bloomed, **story["focus"])
    treated = np.asarray(focused, dtype=np.float32) / 255.0
    treated = add_vignette(treated, story["vignette"])
    treated = apply_color_cast(treated, story["cast"])
    treated = add_grain(treated, rng, story["grain"])
    return Image.fromarray(np.uint8(treated.clip(0.0, 1.0) * 255), mode="RGB")


def _structure_metrics(path: Path) -> dict[str, float]:
    import numpy as np
    from PIL import Image
    from PIL import ImageFilter

    with Image.open(path) as image:
        gray = image.convert("L").filter(ImageFilter.GaussianBlur(8))
        pixels = np.asarray(gray, dtype=np.float32)
        gx = np.abs(np.diff(pixels, axis=1))
        gy = np.abs(np.diff(pixels, axis=0))
        edge_map = np.pad(gx, ((0, 0), (0, 1))) + np.pad(gy, ((0, 1), (0, 0)))
        row = np.asarray(image.convert("L").filter(ImageFilter.GaussianBlur(18)), dtype=np.float32).mean(axis=1)
        row_gradient = np.abs(np.diff(row))
        corners = (
            pixels[:150, :150].mean()
            + pixels[:150, -150:].mean()
            + pixels[-150:, :150].mean()
            + pixels[-150:, -150:].mean()
        ) / 4.0
        lower_cluster = pixels[420:850, 390:1240].mean()
        return {
            "mean": float(pixels.mean()),
            "std": float(pixels.std()),
            "edge_structure": float(np.percentile(edge_map, 99.5)),
            "lower_cluster_minus_corners": float(lower_cluster - corners),
            "horizon_gradient": float(row_gradient[560:640].max()),
        }


def _horizon_scene_metrics(path: Path) -> dict[str, float]:
    import numpy as np
    from PIL import Image
    from PIL import ImageFilter

    with Image.open(path) as image:
        pixels = np.asarray(image.convert("L").filter(ImageFilter.GaussianBlur(18)), dtype=np.float32)
        yy, xx = np.mgrid[0 : pixels.shape[0], 0 : pixels.shape[1]]
        disc = ((xx - 640) ** 2 / (84**2) + (yy - 300) ** 2 / (72**2)) <= 1.0
        ring = (((xx - 640) ** 2 / (150**2) + (yy - 300) ** 2 / (130**2)) <= 1.0) & ~disc

        sky_rows = pixels[110:555].mean(axis=1)
        trend = np.linspace(sky_rows[0], sky_rows[-1], len(sky_rows))
        row_residual = sky_rows - trend

        horizon_gradients = np.abs(np.diff(pixels[600:740], axis=0))
        horizon_y: list[int] = []
        for x_pos in np.linspace(120, 1480, 14, dtype=int):
            column_band = horizon_gradients[:, max(0, x_pos - 35) : min(pixels.shape[1], x_pos + 35)].mean(axis=1)
            horizon_y.append(int(column_band.argmax() + 600))

        center = pixels[260:680, 280:1320].mean()
        corners = (
            pixels[:150, :150].mean()
            + pixels[:150, -150:].mean()
            + pixels[-150:, :150].mean()
            + pixels[-150:, -150:].mean()
        ) / 4.0

        return {
            "sun_lift": float(pixels[disc].mean() - pixels[ring].mean()),
            "sky_band_std": float(row_residual.std()),
            "sky_minus_ground": float(pixels[350:555].mean() - pixels[700:915].mean()),
            "horizon_mean_y": float(np.mean(horizon_y)),
            "horizon_y_range": float(np.max(horizon_y) - np.min(horizon_y)),
            "vignette_drop": float(center - corners),
            "std": float(pixels.std()),
        }


def render_story(story: dict[str, Any]) -> "Image.Image":
    import numpy as np

    rng = np.random.default_rng(story["seed"])
    return apply_film_treatment(compose_scene(story, rng), story, rng)


def save_jpeg(image: "Image.Image", path: Path) -> None:
    for smooth in range(0, 101, 5):
        image.save(path, "JPEG", quality=JPEG_QUALITY, optimize=True, progressive=True, subsampling=2, smooth=smooth)
        if path.stat().st_size <= TARGET_BYTES:
            return

    for quality in range(JPEG_QUALITY - 2, 69, -2):
        image.save(path, "JPEG", quality=quality, optimize=True, progressive=True, subsampling=2, smooth=100)
        if path.stat().st_size <= TARGET_BYTES:
            return
    raise RuntimeError(f"{path} is still over {TARGET_BYTES} bytes after compression")


def generate_all(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    for story in STORIES:
        save_jpeg(render_story(story), output_dir / f"{story['slug']}.jpg")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_self_tests() -> int:
    suite = unittest.defaultTestLoader.loadTestsFromTestCase(GeneratorTests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-test", action="store_true", help="run deterministic output tests")
    args = parser.parse_args()

    if args.self_test:
        return _run_self_tests()

    output_dir = Path(__file__).resolve().parents[1] / "src" / "assets" / "images" / "stories"
    generate_all(output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
