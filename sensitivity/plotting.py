from __future__ import annotations

import html
import math
from pathlib import Path

import numpy as np


WIDTH = 1600
HEIGHT = 900
MARGIN = 110
COLORS = ["#176B5B", "#D97706", "#2563A7", "#A23B72", "#6B7C2A", "#7A4EAB"]


def _text(x, y, value, size=24, anchor="start", weight="normal", color="#17211B", rotate=None):
    transform = f' transform="rotate({rotate} {x} {y})"' if rotate is not None else ""
    return f'<text x="{x:.1f}" y="{y:.1f}" font-family="Arial, sans-serif" font-size="{size}" font-weight="{weight}" fill="{color}" text-anchor="{anchor}"{transform}>{html.escape(str(value))}</text>'


def _document(title: str, elements: list[str], subtitle: str | None = None) -> str:
    heading = [_text(MARGIN, 58, title, 34, weight="bold")]
    if subtitle:
        heading.append(_text(MARGIN, 91, subtitle, 20, color="#52635A"))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}">'
        '<rect width="100%" height="100%" fill="#FFFFFF"/>'
        + "".join(heading + elements)
        + "</svg>"
    )


def _save(path: Path, title: str, elements: list[str], subtitle: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_document(title, elements, subtitle), encoding="utf-8")
    return path


def tornado(path: Path, title: str, rows: list[dict], value_label: str, limit: int = 10) -> Path:
    selected = rows[:limit]
    effects = [abs(value) for row in selected for value in (row["Low_Delta"], row["High_Delta"]) if value is not None]
    extent = max(effects or [1.0]) * 1.15
    left, right, top, bottom = 570, 1490, 135, 805
    centre = (left + right) / 2
    scale = (right - left) / (2 * extent)
    elements = [f'<line x1="{centre}" y1="{top}" x2="{centre}" y2="{bottom}" stroke="#25352D" stroke-width="3"/>']
    row_height = (bottom - top) / max(len(selected), 1)
    for index, row in enumerate(selected):
        y = top + (index + 0.5) * row_height
        low = float(row["Low_Delta"] or 0)
        high = float(row["High_Delta"] or 0)
        for value, color in ((low, COLORS[0]), (high, COLORS[1])):
            x = centre + value * scale
            x0, width = min(centre, x), abs(x - centre)
            elements.append(f'<rect x="{x0:.1f}" y="{y - row_height * 0.24:.1f}" width="{max(width, 1):.1f}" height="{row_height * 0.2:.1f}" fill="{color}"/>')
        elements.append(_text(left - 18, y + 7, row["Parameter_Label"], 19, anchor="end"))
        elements.append(_text(centre + low * scale, y - row_height * 0.09, f"{low:+.4g}", 16, anchor="middle", color=COLORS[0]))
        elements.append(_text(centre + high * scale, y + row_height * 0.30, f"{high:+.4g}", 16, anchor="middle", color=COLORS[1]))
    for tick in np.linspace(-extent, extent, 9):
        x = centre + tick * scale
        elements.append(f'<line x1="{x:.1f}" y1="{bottom}" x2="{x:.1f}" y2="{bottom + 10}" stroke="#25352D"/>')
        elements.append(_text(x, bottom + 38, f"{tick:.3g}", 17, anchor="middle"))
    elements.extend([
        _text((left + right) / 2, 865, value_label, 22, anchor="middle", weight="bold"),
        f'<rect x="{right - 270}" y="55" width="22" height="16" fill="{COLORS[0]}"/>',
        _text(right - 238, 70, "Low scenario", 18),
        f'<rect x="{right - 125}" y="55" width="22" height="16" fill="{COLORS[1]}"/>',
        _text(right - 93, 70, "High scenario", 18),
    ])
    return _save(path, title, elements, "Bars show change from the authoritative baseline")


def line_chart(path: Path, title: str, rows: list[dict], x_key: str, series: list[tuple[str, str]], x_label: str, y_label: str) -> Path:
    left, right, top, bottom = 170, 1490, 145, 760
    xs = np.asarray([float(row[x_key]) for row in rows])
    all_y = [float(row[key]) for row in rows for key, _ in series if row.get(key) is not None]
    ymin, ymax = min(all_y), max(all_y)
    pad = max((ymax - ymin) * 0.12, 0.01)
    ymin, ymax = ymin - pad, ymax + pad
    xpad = max((xs.max() - xs.min()) * 0.03, 0.01)
    xmin, xmax = xs.min() - xpad, xs.max() + xpad
    sx = lambda value: left + (value - xmin) / (xmax - xmin) * (right - left)
    sy = lambda value: bottom - (value - ymin) / (ymax - ymin) * (bottom - top)
    elements = [
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#25352D" stroke-width="2"/>',
        f'<line x1="{left}" y1="{top}" x2="{left}" y2="{bottom}" stroke="#25352D" stroke-width="2"/>',
    ]
    exact_ticks = sorted(set(float(value) for value in xs))
    x_ticks = exact_ticks if len(exact_ticks) <= 11 else list(np.linspace(xs.min(), xs.max(), 6))
    for tick in x_ticks:
        x = sx(tick)
        elements.append(f'<line x1="{x:.1f}" y1="{top}" x2="{x:.1f}" y2="{bottom}" stroke="#E1E8E4"/>')
        if math.isclose(tick, round(tick)) and max(abs(value) for value in exact_ticks) >= 10:
            tick_label = f"{int(round(tick)):,}"
        else:
            tick_label = f"{tick:.2f}".rstrip("0").rstrip(".")
        elements.append(_text(x, bottom + 34, tick_label, 18, anchor="middle"))
    for tick in np.linspace(ymin, ymax, 6):
        y = sy(tick)
        elements.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="#E1E8E4"/>')
        elements.append(_text(left - 16, y + 6, f"{tick:.4g}", 18, anchor="end"))
    for index, (key, label) in enumerate(series):
        color = COLORS[index % len(COLORS)]
        points = [(sx(float(row[x_key])), sy(float(row[key]))) for row in rows if row.get(key) is not None]
        elements.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in points)}" fill="none" stroke="{color}" stroke-width="4"/>')
        for x, y in points:
            elements.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{color}"/>')
        lx = right - 310
        ly = 70 + index * 28
        elements.append(f'<line x1="{lx}" y1="{ly}" x2="{lx + 32}" y2="{ly}" stroke="{color}" stroke-width="5"/>')
        elements.append(_text(lx + 42, ly + 6, label, 18))
    elements.append(_text((left + right) / 2, 850, x_label, 22, anchor="middle", weight="bold"))
    elements.append(_text(42, (top + bottom) / 2, y_label, 22, anchor="middle", weight="bold", rotate=-90))
    return _save(path, title, elements)


def grouped_bars(path: Path, title: str, categories: list[str], series: list[tuple[str, list[float]]], y_label: str) -> Path:
    left, right, top, bottom = 170, 1490, 145, 740
    values = [value for _, group in series for value in group]
    ymin, ymax = min(0.0, min(values)), max(values)
    pad = max((ymax - ymin) * 0.12, 1.0)
    ymin, ymax = ymin - pad * 0.05, ymax + pad
    sy = lambda value: bottom - (value - ymin) / (ymax - ymin) * (bottom - top)
    elements = []
    group_width = (right - left) / max(len(categories), 1)
    bar_width = group_width * 0.72 / max(len(series), 1)
    for tick in np.linspace(ymin, ymax, 6):
        y = sy(tick)
        elements.append(f'<line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="#E1E8E4"/>')
        elements.append(_text(left - 16, y + 6, f"{tick:.4g}", 18, anchor="end"))
    for c_index, category in enumerate(categories):
        x0 = left + c_index * group_width + group_width * 0.14
        for s_index, (label, group) in enumerate(series):
            value = group[c_index]
            x = x0 + s_index * bar_width
            y = sy(value)
            y_zero = sy(0)
            elements.append(f'<rect x="{x:.1f}" y="{min(y, y_zero):.1f}" width="{bar_width * 0.88:.1f}" height="{max(abs(y_zero - y), 1):.1f}" fill="{COLORS[s_index]}"/>')
        elements.append(_text(left + (c_index + 0.5) * group_width, bottom + 36, category, 17, anchor="middle"))
    for index, (label, _) in enumerate(series):
        lx = right - 260
        ly = 64 + index * 28
        elements.append(f'<rect x="{lx}" y="{ly - 15}" width="20" height="16" fill="{COLORS[index]}"/>')
        elements.append(_text(lx + 30, ly, label, 18))
    elements.append(_text(42, (top + bottom) / 2, y_label, 22, anchor="middle", weight="bold", rotate=-90))
    return _save(path, title, elements)


def categorical_modes(path: Path, rows: list[dict]) -> Path:
    mapping = {"unimodal": 0, "indeterminate": 1, "weakly bimodal": 2, "clearly bimodal": 3}
    converted = [{"x": row["Early_Exit_Probability"], "y": mapping[row["Classification"]]} for row in rows]
    left, right, top, bottom = 190, 1480, 145, 740
    sx = lambda value: left + float(value) / max(float(rows[-1]["Early_Exit_Probability"]), 0.01) * (right - left)
    sy = lambda value: bottom - value / 3 * (bottom - top)
    elements = []
    for label, value in mapping.items():
        y = sy(value)
        elements.append(f'<line x1="{left}" y1="{y}" x2="{right}" y2="{y}" stroke="#E1E8E4"/>')
        elements.append(_text(left - 18, y + 7, label, 19, anchor="end"))
    points = [(sx(row["x"]), sy(row["y"])) for row in converted]
    elements.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in points)}" fill="none" stroke="{COLORS[3]}" stroke-width="4"/>')
    for x, y in points:
        elements.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="8" fill="{COLORS[3]}"/>')
    for tick in np.linspace(0, float(rows[-1]["Early_Exit_Probability"]), 6):
        elements.append(_text(sx(tick), bottom + 36, f"{tick:.2f}", 18, anchor="middle"))
    elements.append(_text((left + right) / 2, 850, "Early-exit probability", 22, anchor="middle", weight="bold"))
    return _save(path, "Bimodality Classification versus Early-Exit Probability", elements, "KDE mode prominence and Gaussian-mixture BIC classification")


def hist_kde_panels(path: Path, scenarios: list[dict]) -> Path:
    elements = []
    panel_width = 440
    panel_height = 560
    top = 180
    for index, scenario in enumerate(scenarios):
        x0 = 90 + index * 505
        y0 = top
        values = np.asarray(scenario["values"], dtype=np.float64)
        grid = np.asarray(scenario["grid"])
        density = np.asarray(scenario["density"])
        bins = np.linspace(values.min(), values.max(), 45)
        counts, edges = np.histogram(values, bins=bins, density=True)
        xmax = max(float(density.max()), float(counts.max())) * 1.1
        sx = lambda value: x0 + (value - values.min()) / max(values.max() - values.min(), 1) * panel_width
        sy = lambda value: y0 + panel_height - value / max(xmax, 1e-12) * panel_height
        for count, left_edge, right_edge in zip(counts, edges[:-1], edges[1:]):
            x = sx(left_edge)
            width = sx(right_edge) - x
            y = sy(count)
            elements.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{max(width - 1, 1):.1f}" height="{y0 + panel_height - y:.1f}" fill="#B7C9C0"/>')
        points = [(sx(value), sy(dens)) for value, dens in zip(grid, density) if values.min() <= value <= values.max()]
        elements.append(f'<polyline points="{" ".join(f"{x:.1f},{y:.1f}" for x, y in points)}" fill="none" stroke="{COLORS[1]}" stroke-width="4"/>')
        elements.append(_text(x0 + panel_width / 2, y0 - 28, f"p(e1T) = {scenario['probability']:.2f}", 23, anchor="middle", weight="bold"))
        elements.append(_text(x0 + panel_width / 2, y0 + panel_height + 36, "Mixed-outcome duration (working days)", 17, anchor="middle"))
    return _save(path, "Selected Combined Histograms and KDEs", elements, "Bars are mixed-outcome histograms; orange lines use the documented Silverman-rule KDE")


def ranking_chart(path: Path, rows: list[dict], limit: int = 12) -> Path:
    selected = rows[:limit]
    left, right, top, bottom = 590, 1480, 145, 790
    max_value = max([float(row["Normalised_Influence_Score"]) for row in selected] or [1.0])
    row_height = (bottom - top) / max(len(selected), 1)
    elements = []
    for index, row in enumerate(selected):
        y = top + index * row_height + row_height * 0.18
        value = float(row["Normalised_Influence_Score"])
        width = value / max_value * (right - left)
        elements.append(f'<rect x="{left}" y="{y:.1f}" width="{width:.1f}" height="{row_height * 0.54:.1f}" fill="{COLORS[index % len(COLORS)]}"/>')
        elements.append(_text(left - 18, y + row_height * 0.4, row["Parameter_Label"], 18, anchor="end"))
        elements.append(_text(left + width + 12, y + row_height * 0.4, f"{value:.3f}", 17))
    elements.append(_text((left + right) / 2, 850, "Normalised influence score", 22, anchor="middle", weight="bold"))
    return _save(path, "Integrated Driver Ranking", elements, "Maximum normalised effect across conditional-time and outcome measures")
