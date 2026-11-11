# -*- coding: utf-8 -*-
"""boardcam.trace — детерминированная трассировка эскизов деревянных досок.

OpenCV извлекает внешний контур и контур кармана из фотографии эскиза;
LLM читает только надписи и размеры.
"""

from dataclasses import dataclass, field
import json
import math
import mimetypes
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np
from pydantic import BaseModel, Field as PydanticField
import shapely
from shapely.geometry import Polygon
import shapely.validation


# =============================================================================
# 1. Pydantic-схема ответа LLM и структуры данных
# =============================================================================

class OtherFeature(BaseModel):
    type: str
    x_mm: Optional[float] = None
    y_mm: Optional[float] = None
    d_mm: Optional[float] = None
    depth_mm: Optional[float] = None


class TranscriptionItem(BaseModel):
    label: str
    meaning: str


class LLMSketchSpec(BaseModel):
    rotate_deg: int = PydanticField(default=0)
    outline_size_mm: List[float] = PydanticField(default_factory=lambda: [200.0, 200.0])
    units_detected: str = PydanticField(default="mm")
    thickness_mm: Optional[float] = None
    pocket_depth_mm: Optional[float] = None
    other_features: List[OtherFeature] = PydanticField(default_factory=list)
    transcription: List[TranscriptionItem] = PydanticField(default_factory=list)
    confidence: float = PydanticField(default=1.0)
    assumptions: List[str] = PydanticField(default_factory=list)


@dataclass
class SketchSpec:
    rotate_deg: int = 0
    size_mm: List[float] = field(default_factory=lambda: [200.0, 200.0])
    thickness_mm: float = 22.0
    pocket_depth_mm: float = 12.0
    min_wall_mm: float = 10.0
    bowl_r_mm: float = 6.35
    threshold_method: str = "otsu"  # "otsu" или "adaptive"
    smoothing_strength: float = 1.0
    rdp_tolerance_mm: float = 0.3
    max_contour_points: int = 400
    units_detected: str = "mm"
    other_features: List[Dict[str, Any]] = field(default_factory=list)
    transcription: List[Dict[str, str]] = field(default_factory=list)
    confidence: float = 1.0
    assumptions: List[str] = field(default_factory=list)


@dataclass
class TraceResult:
    outline_pts: List[List[float]] = field(default_factory=list)
    pocket_pts: List[List[float]] = field(default_factory=list)
    scale_px_per_mm: float = 1.0
    scale_mm_per_px: float = 1.0
    size_mm: List[float] = field(default_factory=lambda: [0.0, 0.0])
    bbox_mm: List[float] = field(default_factory=lambda: [0.0, 0.0, 0.0, 0.0])
    warnings: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    success: bool = True
    scad_code: str = ""
    scad_path: Optional[str] = None
    json_path: Optional[str] = None
    debug_path: Optional[str] = None


# =============================================================================
# 2. Предобработка изображения и OpenCV конвейер
# =============================================================================

def get_exif_orientation(image_path: str) -> Optional[int]:
    """Чтение тега Orientation (0x0112) из JPEG без внешних зависимостей."""
    try:
        with open(image_path, "rb") as f:
            data = f.read(65536)
        idx = data.find(b"Exif\x00\x00")
        if idx == -1:
            return None
        tiff = data[idx + 6:]
        endian = "<" if tiff[:2] == b"II" else ">"
        import struct
        magic = struct.unpack(endian + "H", tiff[2:4])[0]
        if magic != 42:
            return None
        ifd0_offset = struct.unpack(endian + "I", tiff[4:8])[0]
        num_entries = struct.unpack(endian + "H", tiff[ifd0_offset:ifd0_offset + 2])[0]
        for i in range(num_entries):
            entry = tiff[ifd0_offset + 2 + i * 12:ifd0_offset + 2 + (i + 1) * 12]
            tag, typ, cnt, val = struct.unpack(endian + "HHI4s", entry)
            if tag == 0x0112:
                return struct.unpack(endian + "H", val[:2])[0]
    except Exception:
        pass
    return None


def rotate_image(img: np.ndarray, deg: int) -> np.ndarray:
    """Поворот изображения.

    90 градусов CCW (или 270 CW) делает фото IMG_2472 вертикальным с черешком внизу.
    deg нормализуется по модулю 360.
    """
    deg = int(deg) % 360
    if deg == 0:
        return img
    elif deg == 90:
        return cv2.rotate(img, cv2.ROTATE_90_COUNTERCLOCKWISE)
    elif deg == 180:
        return cv2.rotate(img, cv2.ROTATE_180)
    elif deg == 270:
        return cv2.rotate(img, cv2.ROTATE_90_CLOCKWISE)
    else:
        # Произвольный угол
        h, w = img.shape[:2]
        center = (w / 2.0, h / 2.0)
        M = cv2.getRotationMatrix2D(center, deg, 1.0)
        return cv2.warpAffine(img, M, (w, h), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def load_image(image_path: str, rotate_deg: int = 0) -> np.ndarray:
    """Загрузка изображения, учёт EXIF и поворот по rotate_deg."""
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Файл изображения не найден: {image_path}")

    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Не удалось прочитать изображение через OpenCV: {image_path}")

    # В OpenCV 4+ IMREAD_COLOR обычно уже применяет EXIF orientation.
    # Дополнительно поворачиваем по spec.rotate_deg:
    if rotate_deg:
        img = rotate_image(img, rotate_deg)
    return img


def extract_ink_mask(img: np.ndarray, thresh_method: str = "otsu", debug: bool = False) -> Tuple[np.ndarray, np.ndarray]:
    """Устранение неравномерного освещения и бинаризация карандашного штриха."""
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Деление на крупный гауссовский фон
    ksize = int(max(h, w) * 0.15) | 1
    bg = cv2.GaussianBlur(gray, (ksize, ksize), 0)
    norm = cv2.divide(gray, bg, scale=255)

    if thresh_method == "adaptive":
        block_size = int(max(h, w) * 0.05) | 1
        ink = cv2.adaptiveThreshold(norm, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY_INV, block_size, 10)
    else:
        # Otsu по умолчанию
        _, ink = cv2.threshold(norm, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    return ink, norm


def filter_junk_and_lines(ink: np.ndarray, norm: np.ndarray, debug: bool = False) -> np.ndarray:
    """Маскирование краёв изображения (~3%), штрихкода, тонких прямых линий и мелкого текста."""
    h, w = img_shape = ink.shape[:2]
    clean_ink = ink.copy()

    # 1. Обнуляем поля по периметру (~3%)
    m_x = max(2, int(w * 0.03))
    m_y = max(2, int(h * 0.03))
    clean_ink[:m_y, :] = 0
    clean_ink[-m_y:, :] = 0
    clean_ink[:, :m_x] = 0
    clean_ink[:, -m_x:] = 0

    # 2. Детектирование прямых линий размерной рамки (HoughLinesP)
    edges = cv2.Canny(norm, 50, 150)
    min_line_len = int(min(h, w) * 0.20)
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=70, minLineLength=min_line_len, maxLineGap=12)
    line_mask = np.zeros_like(clean_ink)
    if lines is not None:
        for x1, y1, x2, y2 in lines.reshape(-1, 4):
            angle = abs(np.arctan2(float(y2 - y1), float(x2 - x1)) * 180.0 / np.pi)
            # Горизонтальные или вертикальные линии
            if angle < 12 or angle > 168 or abs(angle - 90) < 12:
                cv2.line(line_mask, (int(x1), int(y1)), (int(x2), int(y2)), 255, 3)

    # 3. Анализ связных компонент: фильтрация мелкого текста и изолированных размерных линий
    ret, labels, stats, centroids = cv2.connectedComponentsWithStats(clean_ink, connectivity=8)
    filtered = np.zeros_like(clean_ink)

    for i in range(1, ret):
        area = int(stats[i, cv2.CC_STAT_AREA])
        bx = int(stats[i, cv2.CC_STAT_LEFT])
        by = int(stats[i, cv2.CC_STAT_TOP])
        bw = int(stats[i, cv2.CC_STAT_WIDTH])
        bh = int(stats[i, cv2.CC_STAT_HEIGHT])

        # Мелкий шум/отдельные буквы текста
        if area < 25:
            continue

        comp_mask = (labels == i).astype(np.uint8) * 255

        # Проверка на совпадение с размерной линией рамки
        overlap = cv2.bitwise_and(comp_mask, line_mask)
        if np.count_nonzero(overlap) > 0.5 * area and area < 800:
            continue

        # Проверка на полосы штрихкода (высокое соотношение сторон на краю)
        aspect = max(bw, bh) / (min(bw, bh) + 1e-3)
        if (bx > w * 0.85 or by > h * 0.85 or bx < w * 0.15 or by < h * 0.15) and aspect > 8 and area < 400:
            continue

        filtered[labels == i] = 255

    return filtered


def find_outer_outline(filtered_ink: np.ndarray, debug: bool = False) -> Tuple[np.ndarray, np.ndarray, List[str]]:
    """Замыкание контура, flood-fill снаружи и выделение наружного контура доски."""
    h, w = filtered_ink.shape[:2]
    warnings = []

    # Замыкание разрывов карандаша (морфологическое закрытие)
    k_close = max(5, int(max(h, w) * 0.012)) | 1
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_close, k_close))
    closed = cv2.morphologyEx(filtered_ink, cv2.MORPH_CLOSE, kernel)

    # Flood-fill снаружи от углов
    flood = closed.copy()
    f_mask = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(flood, f_mask, (0, 0), 128)
    enclosed = (flood != 128).astype(np.uint8) * 255

    # Поиск контуров
    contours, _ = cv2.findContours(enclosed, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    if not contours:
        raise ValueError("Не найден ни один замкнутый контур на изображении.")

    valid = []
    for c in contours:
        area = cv2.contourArea(c)
        if area < 1000:
            continue
        bx, by, bw, bh = cv2.boundingRect(c)
        # Касается границ кадра
        if bx <= 2 or by <= 2 or bx + bw >= w - 2 or by + bh >= h - 2:
            continue
        # Слишком прямоугольный (размерная рамка)
        rect_ratio = area / float(bw * bh)
        if rect_ratio > 0.94:
            continue
        valid.append(c)

    if not valid:
        # Проверяем, коснулся ли контур границы
        for c in contours:
            if cv2.contourArea(c) > 2000:
                bx, by, bw, bh = cv2.boundingRect(c)
                if bx <= 2 or by <= 2 or bx + bw >= w - 2 or by + bh >= h - 2:
                    raise ValueError("Контур доски касается границы изображения (недопустимо).")
        raise ValueError("Не найден подходящий замкнутый контур доски (все контуры отфильтрованы).")

    # Берём наибольший
    outline = max(valid, key=cv2.contourArea)

    # Маска контура
    outline_mask = np.zeros((h, w), np.uint8)
    cv2.drawContours(outline_mask, [outline], -1, 255, -1)

    return outline, outline_mask, warnings


def find_pocket(clean_ink: np.ndarray, outline_contour: np.ndarray, outline_mask: np.ndarray,
                debug: bool = False) -> Tuple[Optional[np.ndarray], List[str]]:
    """Выделение кармана по локальной плотности штриховки внутри контура доски."""
    h, w = clean_ink.shape[:2]
    warnings = []
    bbox = cv2.boundingRect(outline_contour)
    bw, bh = bbox[2], bbox[3]

    # Сжатие маски контура, чтобы отрезать саму наружную линию доски
    erode_r = max(5, int(min(bw, bh) * 0.04))
    kernel_erode = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (erode_r * 2 + 1, erode_r * 2 + 1))
    inner_mask = cv2.erode(outline_mask, kernel_erode)

    ink_inside = cv2.bitwise_and(clean_ink, inner_mask)

    # Плотность штриховки (размытие)
    k_dens = max(11, int(min(bw, bh) * 0.08)) | 1
    density = cv2.GaussianBlur(ink_inside.astype(np.float32), (k_dens, k_dens), 0)
    max_d = float(np.max(density))

    if max_d > 8.0:
        # Порог плотности: плотная штриховка
        thresh_d = max(6.0, 0.25 * max_d)
        p_mask = (density > thresh_d).astype(np.uint8) * 255

        # Закрытие крупным ядром
        k_pclose = max(11, int(min(bw, bh) * 0.08)) | 1
        kernel_p = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_pclose, k_pclose))
        p_closed = cv2.morphologyEx(p_mask, cv2.MORPH_CLOSE, kernel_p)

        # Заливка внутренних дыр
        pf = p_closed.copy()
        pf_mask = np.zeros((h + 2, w + 2), np.uint8)
        cv2.floodFill(pf, pf_mask, (0, 0), 128)
        p_filled = (pf != 128).astype(np.uint8) * 255

        p_conts, _ = cv2.findContours(p_filled, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        outline_area = cv2.contourArea(outline_contour)
        valid_p = [c for c in p_conts if 0.02 * outline_area < cv2.contourArea(c) < 0.85 * outline_area]
        if valid_p:
            pocket = max(valid_p, key=cv2.contourArea)
            return pocket, warnings

    # Fallback: поиск замкнутой внутренней петли
    k_inner = max(5, int(min(bw, bh) * 0.03)) | 1
    kernel_in = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_inner, k_inner))
    inner_closed = cv2.morphologyEx(ink_inside, cv2.MORPH_CLOSE, kernel_in)
    p_flood = inner_closed.copy()
    p_mask = np.zeros((h + 2, w + 2), np.uint8)
    cv2.floodFill(p_flood, p_mask, (0, 0), 128)
    inner_filled = (p_flood != 128).astype(np.uint8) * 255
    fb_conts, _ = cv2.findContours(inner_filled, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    outline_area = cv2.contourArea(outline_contour)
    valid_fb = [c for c in fb_conts if 0.03 * outline_area < cv2.contourArea(c) < 0.85 * outline_area]
    if valid_fb:
        pocket = max(valid_fb, key=cv2.contourArea)
        warnings.append("Карман выделен через резервный поиск замкнутой внутренней петли.")
        return pocket, warnings

    warnings.append("Карман не обнаружен на эскизе.")
    return None, warnings


# =============================================================================
# 3. Масштабирование, сглаживание и валидация контуров в миллиметрах
# =============================================================================

def periodic_smooth(pts: np.ndarray, strength: float = 1.0) -> np.ndarray:
    """Периодическое гауссовское сглаживание координат замкнутого контура."""
    n = len(pts)
    if n < 6 or strength <= 0:
        return pts

    sigma = max(0.5, float(strength) * 2.0)
    k_radius = int(math.ceil(3 * sigma))
    if k_radius * 2 + 1 >= n:
        k_radius = max(1, (n - 1) // 2)
    indices = np.arange(-k_radius, k_radius + 1)
    kernel = np.exp(-0.5 * (indices / sigma) ** 2)
    kernel /= kernel.sum()

    padded_x = np.pad(pts[:, 0], k_radius, mode="wrap")
    padded_y = np.pad(pts[:, 1], k_radius, mode="wrap")
    smooth_x = np.convolve(padded_x, kernel, mode="valid")
    smooth_y = np.convolve(padded_y, kernel, mode="valid")
    return np.column_stack([smooth_x, smooth_y])


def resample_arc_length(pts: np.ndarray, step_mm: float = 1.0) -> np.ndarray:
    """Передискретизация замкнутого контура по длине дуги с равномерным шагом ~step_mm."""
    n = len(pts)
    if n < 3:
        return pts

    diffs = np.diff(pts, axis=0, append=pts[:1])
    dists = np.hypot(diffs[:, 0], diffs[:, 1])
    total_length = np.sum(dists)
    if total_length < step_mm:
        return pts

    cum_dist = np.concatenate([[0.0], np.cumsum(dists)])
    # Замкнутый ряд координат для интерполяции
    loop_pts = np.vstack([pts, pts[:1]])

    num_samples = max(8, int(round(total_length / step_mm)))
    sample_dists = np.linspace(0.0, total_length, num_samples, endpoint=False)

    sampled_x = np.interp(sample_dists, cum_dist, loop_pts[:, 0])
    sampled_y = np.interp(sample_dists, cum_dist, loop_pts[:, 1])
    return np.column_stack([sampled_x, sampled_y])


def clean_and_simplify_contour(pts_mm: np.ndarray, rdp_tolerance: float = 0.3,
                               max_points: int = 400, strength: float = 1.0) -> List[List[float]]:
    """Периодическое сглаживание, ресемплинг, RDP-упрощение, ориентация CCW и валидация через shapely."""
    # 1. Периодическое сглаживание
    smoothed = periodic_smooth(pts_mm, strength=strength)

    # 2. Ресемплинг с шагом ~1.0 мм
    resampled = resample_arc_length(smoothed, step_mm=1.0)

    # 3. Формирование полигона в Shapely
    poly = Polygon(resampled)
    if not poly.is_valid:
        poly = shapely.validation.make_valid(poly)
        if hasattr(poly, "geoms"):
            poly = max(poly.geoms, key=lambda g: g.area)

    # 4. RDP-упрощение с адаптивным подбором допуска до <= max_points
    tol = rdp_tolerance
    simplified_poly = poly.simplify(tol, preserve_topology=True)
    coords = list(simplified_poly.exterior.coords)[:-1]

    while len(coords) > max_points and tol < 3.0:
        tol += 0.1
        simplified_poly = poly.simplify(tol, preserve_topology=True)
        coords = list(simplified_poly.exterior.coords)[:-1]

    # 5. Ориентация CCW (против часовой стрелки)
    poly_oriented = shapely.geometry.polygon.orient(Polygon(coords), sign=1.0)
    final_pts = [[round(float(p[0]), 3), round(float(p[1]), 3)] for p in list(poly_oriented.exterior.coords)[:-1]]
    return final_pts


def transform_contours(outline_c: np.ndarray, pocket_c: Optional[np.ndarray],
                       spec: SketchSpec) -> Tuple[List[List[float]], List[List[float]], float, float, List[str]]:
    """Масштабирование к spec.size_mm, отражение Y и центрирование (0,0) по контракту leaf.scad."""
    warnings = []
    bx, by, bw, bh = cv2.boundingRect(outline_c)
    if bw <= 0 or bh <= 0:
        raise ValueError("Некорректный размер ограничивающего прямоугольника контура.")

    target_w, target_h = float(spec.size_mm[0]), float(spec.size_mm[1])
    scale_x = target_w / float(bw)
    scale_y = target_h / float(bh)

    diff = abs(scale_x - scale_y) / max(scale_x, scale_y)
    if diff > 0.03:
        warnings.append(
            f"Соотношение сторон контура отличается от заявленного {target_w:.1f}x{target_h:.1f} на {diff * 100:.1f}%. "
            f"Используется равномерный масштаб по большей стороне."
        )

    # Равномерный масштаб по большей стороне
    scale_mm_per_px = max(target_w, target_h) / float(max(bw, bh))
    scale_px_per_mm = 1.0 / scale_mm_per_px

    # Центрирование в (0, 0)
    cx_px = bx + bw / 2.0
    cy_px = by + bh / 2.0

    def to_mm(pts_px: np.ndarray) -> np.ndarray:
        pts = pts_px.reshape(-1, 2).astype(np.float64)
        x_mm = (pts[:, 0] - cx_px) * scale_mm_per_px
        # Переворот оси Y (в картинке Y вниз, в CAD Y вверх)
        y_mm = -(pts[:, 1] - cy_px) * scale_mm_per_px
        return np.column_stack([x_mm, y_mm])

    outline_mm_raw = to_mm(outline_c)
    outline_clean = clean_and_simplify_contour(
        outline_mm_raw,
        rdp_tolerance=spec.rdp_tolerance_mm,
        max_points=spec.max_contour_points,
        strength=spec.smoothing_strength
    )

    pocket_clean = []
    if pocket_c is not None:
        pocket_mm_raw = to_mm(pocket_c)
        pocket_clean = clean_and_simplify_contour(
            pocket_mm_raw,
            rdp_tolerance=spec.rdp_tolerance_mm,
            max_points=spec.max_contour_points,
            strength=spec.smoothing_strength
        )

    return outline_clean, pocket_clean, scale_px_per_mm, scale_mm_per_px, warnings


def validate_contours(outline_pts: List[List[float]], pocket_pts: List[List[float]],
                      spec: SketchSpec, blank_x: float, blank_y: float) -> Tuple[Dict[str, Any], List[str], List[str]]:
    """Валидация геометрии: зазор кармана до края, вписывание в заготовку, площадь."""
    warnings = []
    errors = []
    metrics = {}

    outline_poly = Polygon(outline_pts)
    if not outline_poly.is_valid:
        outline_poly = shapely.validation.make_valid(outline_poly)

    min_x, min_y, max_x, max_y = outline_poly.bounds
    actual_w = max_x - min_x
    actual_h = max_y - min_y
    metrics["outline_width_mm"] = round(actual_w, 2)
    metrics["outline_height_mm"] = round(actual_h, 2)
    metrics["outline_area_cm2"] = round(outline_poly.area / 100.0, 2)
    metrics["outline_points_count"] = len(outline_pts)

    # Проверка заготовки
    if actual_w + 20.0 > blank_x or actual_h + 20.0 > blank_y:
        errors.append(
            f"Контур ({actual_w:.1f} x {actual_h:.1f} мм) не помещается в заготовку "
            f"{blank_x:.1f} x {blank_y:.1f} мм с полями 10 мм."
        )

    if pocket_pts:
        pocket_poly = Polygon(pocket_pts)
        if not pocket_poly.is_valid:
            pocket_poly = shapely.validation.make_valid(pocket_poly)

        metrics["pocket_area_cm2"] = round(pocket_poly.area / 100.0, 2)
        metrics["pocket_points_count"] = len(pocket_pts)

        # Проверка, что карман внутри контура
        if not outline_poly.contains(pocket_poly):
            warnings.append("Часть кармана выходит за пределы наружного контура!")

        # Измерение минимального расстояния до наружного контура
        measured_wall = outline_poly.exterior.distance(pocket_poly)
        metrics["measured_min_wall_mm"] = round(measured_wall, 2)

        if measured_wall < spec.min_wall_mm:
            warnings.append(
                f"Минимальная стенка до края {measured_wall:.2f} мм меньше заданной "
                f"min_wall_mm ({spec.min_wall_mm:.2f} мм)."
            )
    else:
        metrics["pocket_area_cm2"] = 0.0
        metrics["pocket_points_count"] = 0
        metrics["measured_min_wall_mm"] = None

    return metrics, warnings, errors


# =============================================================================
# 4. Генерация OpenSCAD по контракту leaf.scad
# =============================================================================

SCAD_TEMPLATE = """// =============================================================================
//  Traced sketch board — сгенерировано boardcam.trace
// =============================================================================
//  Контур и карман извлечены детерминированно из эскиза через OpenCV.
//  Контракт boardcam совпадает с leaf.scad (кленовый лист).
// =============================================================================

/* [Заготовка] */
// Заготовка по X, мм
blank_x = {blank_x};         // [150:5:800]
// Заготовка по Y, мм
blank_y = {blank_y};         // [150:5:800]
// Толщина заготовки, мм
blank_thick = {blank_thick}; // [12:1:60]

/* [Изделие] */
// Габарит изделия по X, мм
size_x = {size_x};           // [100:2:760]
// Габарит изделия по Y, мм
size_y = {size_y};           // [100:2:760]
// Высота, мм
thick = {thick};             // [12:1:60]
// Скругление остриёв наружного контура, мм
tip_r = 5;                   // [3:0.5:20]
// Скругление выемок наружного контура, мм
notch_r = 5;                 // [4:0.5:20]
// Ширина бортика, мм
rim_w = {rim_w};             // [6:1:40]
// Глубина кармана, мм
pocket_depth = {pocket_depth}; // [4:0.5:20]
// Скругление выступов кармана в плане, мм
pocket_r = 12;               // [6:0.5:40]

/* [Hidden] */
export = "";
seg_2d = 0.5;
seg_3d = 2.0;
floor_style = "steps";
floor_steps = 12;
bowl_r = {bowl_r};

// ---------------------------------------------------------------- геометрия ---

outline_pts = [
{outline_points_str}
];

{pocket_pts_definition}

function fn_for(r, seg) = max(16, ceil(2 * PI * r / seg));

module outline_region(seg) {{
    offset(r = -notch_r, $fn = fn_for(notch_r, seg)) offset(delta = notch_r)
        offset(r = tip_r, $fn = fn_for(tip_r, seg)) offset(delta = -tip_r)
            polygon(outline_pts);
}}

{feature_region_module}

module feature_cut(k, seg) {{
    eps = 0.01;
    if (floor_style == "exact") {{
        minkowski() {{
            translate([0, 0, -pocket_depth + bowl_r])
                linear_extrude(pocket_depth + 2) offset(delta = -bowl_r) feature_region(k, seg);
            sphere(r = bowl_r, $fn = 32);
        }}
    }} else {{
        for (s = [0 : floor_steps - 1]) {{
            h0 = bowl_r * (1 - cos(90 * s / floor_steps));
            h1 = bowl_r * (1 - cos(90 * (s + 1) / floor_steps));
            d  = bowl_r * (1 - sin(90 * (s + 0.5) / floor_steps));
            if (h0 < pocket_depth)
                translate([0, 0, -pocket_depth + h0 - eps])
                    linear_extrude(min(h1, pocket_depth + 1) - h0 + 2 * eps)
                        offset(delta = -d) feature_region(k, seg);
        }}
        if (pocket_depth > bowl_r)
            translate([0, 0, -pocket_depth + bowl_r - eps])
                linear_extrude(pocket_depth - bowl_r + 1 + eps) feature_region(k, seg);
    }}
}}

module model() {{
    $fa = 2;
    difference() {{
        translate([0, 0, -thick]) linear_extrude(thick) outline_region(seg_3d);
        {model_feature_cuts}
    }}
}}

// ------------------------------------------------------------- контракт boardcam ---

function messages() = concat(
    (pocket_depth > thick - 3)
        ? [["error", "TOO_DEEP", str("глубина отсека ", pocket_depth, " оставляет дну меньше 3 мм при высоте ", thick)]] : [],
    (max(size_x, size_y) + 20 > min(blank_x, blank_y))
        ? [["error", "BLANK_SMALL", str("доска ", max(size_x, size_y), " мм не помещается в заготовку ", blank_x, " x ", blank_y, " с полями 10 мм")]] : []
);
function has_error() = len([for (m = messages()) if (m[0] == "error") m]) > 0;

echo(boardcam_design = [
    ["schema", 1], ["shape", "traced_sketch"], ["variant", "sketch"], ["units", "mm"],
    ["blank", [blank_x, blank_y, blank_thick]], ["origin", "corner"],
    ["thick", thick],
    ["outline", ["svg", "outline"]],
    ["features", {features_echo_list}],
    ["derived", [["wall_min", rim_w], ["size", max(size_x, size_y)]]],
    ["messages", messages()]
]);

if (!has_error()) {{
    if (export == "") {{
        model();
    }} else if (export == "outline") {{
        outline_region(seg_2d);
    }} {export_pocket_branch}
}}
"""


def generate_scad(trace_result: TraceResult, spec: SketchSpec) -> str:
    """Генерация файла .scad с точным соблюдением контракта leaf.scad."""
    outline_lines = [f"    [{p[0]:.2f}, {p[1]:.2f}]" for p in trace_result.outline_pts]
    outline_points_str = ",\n".join(outline_lines)

    actual_w = trace_result.metrics.get("outline_width_mm", spec.size_mm[0])
    actual_h = trace_result.metrics.get("outline_height_mm", spec.size_mm[1])
    blank_x = math.ceil((actual_w + 40.0) / 10.0) * 10.0
    blank_y = math.ceil((actual_h + 40.0) / 10.0) * 10.0
    blank_thick = spec.thickness_mm

    has_pocket = bool(trace_result.pocket_pts)

    if has_pocket:
        pocket_lines = [f"    [{p[0]:.2f}, {p[1]:.2f}]" for p in trace_result.pocket_pts]
        pocket_points_str = ",\n".join(pocket_lines)
        pocket_pts_definition = f"pocket_pts = [\n{pocket_points_str}\n];"
        feature_region_module = """module feature_region(k, seg) {
    offset(r = -3, $fn = fn_for(3, seg)) offset(delta = 3)
        offset(r = pocket_r, $fn = fn_for(pocket_r, seg)) offset(delta = -pocket_r)
            polygon(pocket_pts);
}"""
        model_feature_cuts = "feature_cut(1, seg_3d);"
        features_echo_list = '[["pocket", 1, ["svg", "pocket:1"], pocket_depth, bowl_r]]'
        export_pocket_branch = 'else if (export == "pocket:1") {\n        feature_region(1, seg_2d);\n    }'
    else:
        pocket_pts_definition = "pocket_pts = [];"
        feature_region_module = """module feature_region(k, seg) {
    square([1, 1]);
}"""
        model_feature_cuts = "// карман не обнаружен"
        features_echo_list = "[]"
        export_pocket_branch = ""

    rim_w = trace_result.metrics.get("measured_min_wall_mm") or spec.min_wall_mm

    scad = SCAD_TEMPLATE.format(
        blank_x=blank_x,
        blank_y=blank_y,
        blank_thick=blank_thick,
        size_x=actual_w,
        size_y=actual_h,
        thick=spec.thickness_mm,
        rim_w=round(rim_w, 1),
        pocket_depth=spec.pocket_depth_mm,
        bowl_r=spec.bowl_r_mm,
        outline_points_str=outline_points_str,
        pocket_pts_definition=pocket_pts_definition,
        feature_region_module=feature_region_module,
        model_feature_cuts=model_feature_cuts,
        features_echo_list=features_echo_list,
        export_pocket_branch=export_pocket_branch
    )
    return scad


def render_debug_image(img_upright: np.ndarray, outline_c: np.ndarray,
                       pocket_c: Optional[np.ndarray], trace_result: TraceResult,
                       spec: SketchSpec, out_path: str) -> None:
    """Создание debug.png с нанесённым контуром, карманом, размерами и пояснениями."""
    dbg = img_upright.copy()

    # Зелёный наружный контур
    cv2.drawContours(dbg, [outline_c], -1, (0, 255, 0), 2)

    # Красный контур кармана
    if pocket_c is not None:
        cv2.drawContours(dbg, [pocket_c], -1, (0, 0, 255), 2)

    # Синяя габаритная рамка
    bx, by, bw, bh = cv2.boundingRect(outline_c)
    cv2.rectangle(dbg, (bx, by), (bx + bw, by + bh), (255, 0, 0), 1)

    # Информационные надписи
    font = cv2.FONT_HERSHEY_SIMPLEX
    scale = 0.5
    color = (20, 20, 20)
    bg_color = (240, 240, 240)

    lines = [
        f"BoardCam Trace: {spec.size_mm[0]:.0f}x{spec.size_mm[1]:.0f} mm (scale: {trace_result.scale_px_per_mm:.2f} px/mm)",
        f"Outline: {len(trace_result.outline_pts)} pts | Area: {trace_result.metrics.get('outline_area_cm2', 0)} cm2",
        f"Pocket: {len(trace_result.pocket_pts)} pts | Area: {trace_result.metrics.get('pocket_area_cm2', 0)} cm2",
        f"Min wall: {trace_result.metrics.get('measured_min_wall_mm', 'N/A')} mm (target: {spec.min_wall_mm} mm)",
    ]
    if trace_result.warnings:
        lines.append(f"Warnings: {len(trace_result.warnings)}")

    y_text = 20
    for line in lines:
        (tw, th), _ = cv2.getTextSize(line, font, scale, 1)
        cv2.rectangle(dbg, (10, y_text - th - 4), (15 + tw, y_text + 4), bg_color, -1)
        cv2.putText(dbg, line, (12, y_text), font, scale, color, 1, cv2.LINE_AA)
        y_text += 22

    cv2.imwrite(out_path, dbg)


# =============================================================================
# 5. Интеграция с DeepSeek Flash LLM
# =============================================================================

LLM_SYSTEM_PROMPT = """You are a technical drawing reading assistant.
You read handwritten dimensions, annotations, and orientation from a photo of a charcuterie board sketch.
DO NOT output code. Output ONLY valid JSON matching this exact schema:

{
  "rotate_deg": 0|90|180|270,
  "outline_size_mm": [w, h],
  "units_detected": "mm"|"inch",
  "thickness_mm": number|null,
  "pocket_depth_mm": number|null,
  "other_features": [
    {"type": "hole|slot|groove", "x_mm": 0, "y_mm": 0, "d_mm": 0, "depth_mm": 0}
  ],
  "transcription": [
    {"label": "text as read", "meaning": "what it dimensions"}
  ],
  "confidence": 0.0-1.0,
  "assumptions": ["string"]
}

Rules:
- rotate_deg: rotation angle needed to make the drawing and text upright (0, 90, 180, or 270).
  Use 90 if rotating 90 degrees counter-clockwise (270 clockwise) makes it upright.
- outline_size_mm: overall bounding box dimensions stated on the drawing. If only one square dimension is given (e.g. 200 MM), use [200, 200].
- units_detected: "mm" or "inch". If units are inches, convert them to mm in outline_size_mm, thickness_mm, and pocket_depth_mm.
- Missing values should be null and explained in assumptions.
- Do NOT output markdown code fences (```json). Output ONLY the raw JSON object.
"""


def call_llm_for_spec(image_path: str, api_key: Optional[str] = None) -> SketchSpec:
    """Вызов DeepSeek-flash для чтения размеров и текстовых меток эскиза."""
    key = api_key or os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("MOONSHOT_API_KEY")
    if not key:
        return SketchSpec(assumptions=["DEEPSEEK_API_KEY не задан; использованы размеры по умолчанию."])

    import base64
    from openai import OpenAI

    mime = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    with open(image_path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    client = OpenAI(api_key=key, base_url="https://api.deepseek.com")

    messages = [
        {"role": "system", "content": LLM_SYSTEM_PROMPT},
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                {"type": "text", "text": "Extract sketch dimensions and orientation as JSON."},
            ],
        },
    ]

    for attempt in range(2):
        resp = client.chat.completions.create(
            model="deepseek-flash",
            temperature=0.0,
            messages=messages,
        )
        content = resp.choices[0].message.content.strip()
        content = re.sub(r"^```[a-zA-Z]*\s*", "", content)
        content = re.sub(r"\s*```$", "", content)

        try:
            data = json.loads(content)
            parsed = LLMSketchSpec.model_validate(data)

            # Перевод дюймов в мм если нужно
            mult = 25.4 if parsed.units_detected == "inch" else 1.0
            size_mm = [s * mult for s in parsed.outline_size_mm]

            thick = (parsed.thickness_mm * mult) if parsed.thickness_mm else 22.0
            p_depth = (parsed.pocket_depth_mm * mult) if parsed.pocket_depth_mm else 12.0

            assumptions = list(parsed.assumptions)
            if not parsed.thickness_mm:
                assumptions.append("Толщина не указана на эскизе; принято значение по умолчанию 22 мм.")
            if not parsed.pocket_depth_mm:
                assumptions.append("Глубина кармана не указана на эскизе; принято значение по умолчанию 12 мм.")

            return SketchSpec(
                rotate_deg=parsed.rotate_deg,
                size_mm=size_mm,
                thickness_mm=thick,
                pocket_depth_mm=p_depth,
                units_detected=parsed.units_detected,
                other_features=[f.model_dump() for f in parsed.other_features],
                transcription=[t.model_dump() for t in parsed.transcription],
                confidence=parsed.confidence,
                assumptions=assumptions,
            )
        except Exception as err:
            if attempt == 0:
                messages.append({"role": "assistant", "content": content})
                messages.append({
                    "role": "user",
                    "content": f"JSON failed schema validation: {err}. Please fix and return ONLY valid JSON.",
                })
            else:
                return SketchSpec(assumptions=[f"Ошибка валидации ответа LLM ({err}); применены параметры по умолчанию."])

    return SketchSpec(assumptions=["Не удалось получить валидный JSON от LLM; применены параметры по умолчанию."])


# =============================================================================
# 6. Главная функция трассировки: trace_sketch
# =============================================================================

def trace_sketch(image_path: str, spec: Optional[SketchSpec] = None,
                 out_dir: Optional[str] = None, debug: bool = False) -> TraceResult:
    """Детерминированная трассировка эскиза доски.

    Функция выполняет полный конвейер:
      1. Загрузка фото, EXIF и поворот;
      2. Выравнивание освещения и бинаризация штриха;
      3. Фильтрация размерных рамок, текста и штрихкода;
      4. Выделение наружного контура через замыкание и flood-fill;
      5. Выделение кармана по плотности штриховки;
      6. Масштабирование, сглаживание и RDP-упрощение;
      7. Валидация геометрии в мм;
      8. Экспорт trace.json, debug.png и .scad по контракту leaf.scad.
    """
    if spec is None:
        spec = SketchSpec()

    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    else:
        out_dir = "."

    result = TraceResult()
    result.size_mm = list(spec.size_mm)

    # 1. Загрузка и поворот
    try:
        img_upright = load_image(image_path, spec.rotate_deg)
    except Exception as e:
        result.success = False
        result.errors.append(str(e))
        return result

    # 2. Выравнивание фона и маска карандаша
    ink_mask, norm_gray = extract_ink_mask(img_upright, thresh_method=spec.threshold_method, debug=debug)

    # 3. Фильтрация мусора
    filtered_ink = filter_junk_and_lines(ink_mask, norm_gray, debug=debug)

    if debug:
        cv2.imwrite(os.path.join(out_dir, "debug_01_norm.png"), norm_gray)
        cv2.imwrite(os.path.join(out_dir, "debug_02_ink.png"), ink_mask)
        cv2.imwrite(os.path.join(out_dir, "debug_03_filtered.png"), filtered_ink)

    # 4. Наружный контур
    try:
        outline_c, outline_mask, w_out = find_outer_outline(filtered_ink, debug=debug)
        result.warnings.extend(w_out)
    except Exception as e:
        result.success = False
        result.errors.append(str(e))
        # Сохраняем debug.png даже при ошибке
        dbg_err = img_upright.copy()
        cv2.putText(dbg_err, f"ERROR: {e}", (20, 40), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        debug_path = os.path.join(out_dir, "debug.png")
        cv2.imwrite(debug_path, dbg_err)
        result.debug_path = debug_path
        return result

    # 5. Карман
    pocket_c, w_pock = find_pocket(filtered_ink, outline_c, outline_mask, debug=debug)
    result.warnings.extend(w_pock)

    # 6. Масштабирование, сглаживание, RDP-упрощение
    try:
        outline_pts, pocket_pts, scale_px, scale_mm, w_trans = transform_contours(outline_c, pocket_c, spec)
        result.outline_pts = outline_pts
        result.pocket_pts = pocket_pts
        result.scale_px_per_mm = scale_px
        result.scale_mm_per_px = scale_mm
        result.warnings.extend(w_trans)
    except Exception as e:
        result.success = False
        result.errors.append(str(e))
        return result

    # 7. Валидация геометрии
    blank_x = math.ceil((spec.size_mm[0] + 40.0) / 10.0) * 10.0
    blank_y = math.ceil((spec.size_mm[1] + 40.0) / 10.0) * 10.0
    metrics, w_val, e_val = validate_contours(outline_pts, pocket_pts, spec, blank_x, blank_y)
    result.metrics = metrics
    result.warnings.extend(w_val)
    result.errors.extend(e_val)
    if e_val:
        result.success = False

    # 8. Генерация SCAD
    scad_code = generate_scad(result, spec)
    result.scad_code = scad_code
    scad_path = os.path.join(out_dir, "board.scad")
    with open(scad_path, "w", encoding="utf-8") as f:
        f.write(scad_code)
    result.scad_path = scad_path

    # 9. Отрисовка debug.png
    debug_path = os.path.join(out_dir, "debug.png")
    render_debug_image(img_upright, outline_c, pocket_c, result, spec, debug_path)
    result.debug_path = debug_path

    # 10. Сохранение trace.json
    trace_data = {
        "outline_pts": result.outline_pts,
        "pocket_pts": result.pocket_pts,
        "scale_px_per_mm": round(result.scale_px_per_mm, 4),
        "scale_mm_per_px": round(result.scale_mm_per_px, 4),
        "size_mm": spec.size_mm,
        "metrics": result.metrics,
        "warnings": result.warnings,
        "errors": result.errors,
        "success": result.success,
        "assumptions": spec.assumptions,
    }
    json_path = os.path.join(out_dir, "trace.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(trace_data, f, ensure_ascii=False, indent=2)
    result.json_path = json_path

    return result


# =============================================================================
# 7. Точка входа командной строки (CLI)
# =============================================================================

def parse_args(argv=None):
    import argparse
    parser = argparse.ArgumentParser(
        prog="boardcam.trace",
        description="Детерминированная трассировка эскиза доски (OpenCV + чтение размеров LLM)."
    )
    parser.add_argument("image", help="Путь к фотографии эскиза (JPG/PNG)")
    parser.add_argument("--size", help="Размер габарита наружного контура, например 200x200 (мм)")
    parser.add_argument("--thickness", type=float, help="Толщина доски, мм (по умолчанию 22)")
    parser.add_argument("--pocket-depth", type=float, help="Глубина кармана, мм (по умолчанию 12)")
    parser.add_argument("--min-wall", type=float, default=10.0, help="Минимальная ширина стенки, мм (по умолчанию 10)")
    parser.add_argument("--rotate", type=int, choices=[0, 90, 180, 270], help="Угол поворота для вертикального положения (0, 90, 180, 270)")
    parser.add_argument("--threshold", choices=["otsu", "adaptive"], default="otsu", help="Метод бинаризации")
    parser.add_argument("--out", default="out", help="Каталог для выходных файлов (trace.json, debug.png, board.scad)")
    parser.add_argument("--debug", action="store_true", help="Печать подробностей и запись промежуточных масок")
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)

    # Если какие-то флаги опущены, запрашиваем LLM
    spec = None
    flags_complete = (args.size is not None and args.thickness is not None and
                      args.pocket_depth is not None and args.rotate is not None)

    if not flags_complete and (os.environ.get("DEEPSEEK_API_KEY") or os.environ.get("MOONSHOT_API_KEY")):
        print(f"-> Запрос к DeepSeek-flash для чтения надписей и размеров с {args.image}...")
        try:
            spec = call_llm_for_spec(args.image)
            print(f"   LLM ответил: поворот {spec.rotate_deg}°, габариты {spec.size_mm} мм, единицы {spec.units_detected}")
        except Exception as e:
            print(f"   Внимание: ошибка вызова LLM ({e}), используем значения по умолчанию.")

    if spec is None:
        spec = SketchSpec()

    # Флаги CLI имеют наивысший приоритет
    if args.rotate is not None:
        spec.rotate_deg = args.rotate
    if args.thickness is not None:
        spec.thickness_mm = args.thickness
    if args.pocket_depth is not None:
        spec.pocket_depth_mm = args.pocket_depth
    if args.min_wall is not None:
        spec.min_wall_mm = args.min_wall
    if args.threshold is not None:
        spec.threshold_method = args.threshold

    if args.size:
        parts = args.size.lower().replace("х", "x").split("x")
        if len(parts) == 2:
            spec.size_mm = [float(parts[0]), float(parts[1])]
        elif len(parts) == 1:
            val = float(parts[0])
            spec.size_mm = [val, val]

    print(f"-> Трассировка {args.image}...")
    print(f"   Параметры: поворот={spec.rotate_deg}°, размер={spec.size_mm} мм, толщина={spec.thickness_mm} мм, глубина кармана={spec.pocket_depth_mm} мм")

    res = trace_sketch(args.image, spec=spec, out_dir=args.out, debug=args.debug)

    if res.success:
        print("✓ Трассировка успешно завершена!")
        print(f"   Точек контура: {len(res.outline_pts)}, точек кармана: {len(res.pocket_pts)}")
        print(f"   Масштаб: {res.scale_px_per_mm:.2f} px/мм ({res.scale_mm_per_px:.4f} мм/px)")
        if res.metrics.get("measured_min_wall_mm") is not None:
            print(f"   Минимальная стенка: {res.metrics['measured_min_wall_mm']} мм")
        print(f"   Сохранено -> {res.scad_path}")
        print(f"   Отчёт     -> {res.json_path}")
        print(f"   Превью    -> {res.debug_path}")
        if res.warnings:
            for w in res.warnings:
                print(f"   [Предупреждение] {w}")
        return 0
    else:
        print("✗ Ошибка трассировки:")
        for err in res.errors:
            print(f"   [Ошибка] {err}")
        if res.debug_path:
            print(f"   Диагностическое изображение: {res.debug_path}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
