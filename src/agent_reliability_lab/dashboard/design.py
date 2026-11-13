"""Design tokens and accessible presentation primitives for the local dashboard."""

import json
from datetime import datetime
from html import escape
from pathlib import Path

import streamlit as st

from agent_reliability_lab.agent.journal import Redactor

COLORS = {
    "azure": "#007BFF",
    "royal": "#1A5FED",
    "coral": "#FF8B6A",
    "lavender": "#B58BE8",
    "white": "#FFFFFF",
    "canvas": "#F0F0F0",
    "border": "#D0D0D0",
    "ink": "#111111",
    "muted": "#475569",
    "blue-ink": "#15439D",
    "blue-wash": "#EAF2FF",
    "purple-ink": "#613E8D",
    "purple-wash": "#F4EDFC",
    "coral-ink": "#893A27",
    "coral-wash": "#FFF0EA",
    "green-ink": "#17604B",
    "green-wash": "#E6F5EF",
}

PURPOSES = {
    "scripted_infrastructure_validation": "Scripted infrastructure validation",
    "live_evaluation": "Live-model evaluation",
}


def streamlit_theme():
    """Explicit light defaults for native widgets, including installed wheels."""
    return {
        "STREAMLIT_THEME_BASE": "light",
        "STREAMLIT_THEME_PRIMARY_COLOR": COLORS["royal"],
        "STREAMLIT_THEME_BACKGROUND_COLOR": COLORS["canvas"],
        "STREAMLIT_THEME_SECONDARY_BACKGROUND_COLOR": COLORS["white"],
        "STREAMLIT_THEME_TEXT_COLOR": COLORS["ink"],
        "STREAMLIT_THEME_BORDER_COLOR": COLORS["border"],
        "STREAMLIT_THEME_SIDEBAR_BACKGROUND_COLOR": COLORS["white"],
        "STREAMLIT_THEME_SIDEBAR_SECONDARY_BACKGROUND_COLOR": COLORS["canvas"],
    }


def styles():
    tokens = "".join(f"--lab-{name}: {value};" for name, value in COLORS.items())
    css = Path(__file__).with_name("theme.css").read_text(encoding="utf-8")
    st.html(f"<style>:root {{{tokens}}}\n{css}</style>")


def plain(value):
    return "Unavailable" if value is None else str(value)


def html(value):
    return escape(plain(value), quote=True)


def title_case(value):
    return str(value).replace("_", " ").capitalize() if value else "Unavailable"


def timestamp(value):
    if not value:
        return "Unavailable"
    if not isinstance(value, datetime):
        try:
            value = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return "Unavailable"
    return value.strftime("%Y-%m-%d %H:%M %Z").strip()


def purpose(record):
    value = record.get("purpose")
    if value == "scripted_infrastructure_validation" and record.get("demonstration") is True:
        return "Synthetic demonstration"
    return (
        PURPOSES.get(value, "Purpose unavailable")
        if isinstance(value, str)
        else "Purpose unavailable"
    )


def bounded(value):
    value = Redactor().clean(value)
    text = json.dumps(value, default=str, ensure_ascii=False)
    if len(text) > 100_000:
        return {"preview_truncated": True, "preview": text[:100_000]}
    return value


def header(title, description, *, hero=False):
    if hero:
        st.html(
            '<header class="lab-hero"><div class="lab-hero-content">'
            f"<h1>{html(title)}</h1><p>{html(description)}</p></div></header>"
        )
    else:
        st.title(title, anchor=False)
        st.caption(description)


def fields(items):
    """Compact key/value strip with escaped data and no widget side effects."""
    content = "".join(
        f"<div><dt>{html(label)}</dt><dd>{html(value)}</dd></div>" for label, value in items
    )
    st.html(f'<dl class="lab-fields">{content}</dl>')


def status_text(value, *, yes="Verified", no="No"):
    if value is True:
        return yes
    if value is False:
        return no
    return "Unknown"


def metric_text(record):
    value = record.get("value")
    if value is not None:
        display = f"{value:.1%}"
        status = "Measured"
    elif record.get("status") == "not_applicable":
        display = status = "Not applicable"
    elif record.get("denominator") == 0:
        display = "Unavailable"
        status = "Insufficient evidence"
    else:
        display = "Unavailable"
        status = "Data unavailable"
    counts = f"{plain(record.get('numerator'))} / {plain(record.get('denominator'))}"
    return display, counts, status


def metric_cards(items, version):
    cards = []
    for label, record, description, tone in items:
        display, counts, status = metric_text(record)
        reason = record.get("reason")
        detail = f"{description} {title_case(reason)}." if reason else description
        value_class = (
            "lab-value" if record.get("value") is not None else "lab-value lab-value-unavailable"
        )
        cards.append(
            f'<article class="lab-kpi lab-{html(tone)}"><h3>{html(label)}</h3>'
            f'<p class="{value_class}">{html(display)}</p>'
            f'<p class="lab-kpi-meta">{html(counts)} <span>· Evaluator {html(version)}</span></p>'
            f'<p class="lab-kpi-description">{html(description)}</p>'
            f'<details class="lab-definition"><summary title="{html(detail)}">'
            f"{html(status)}</summary>"
            f"<p>{html(detail)}</p></details></article>"
        )
    st.html(f'<section class="lab-kpi-grid" aria-label="Cohort metrics">{"".join(cards)}</section>')


def bar_chart(groups, *, label, percent=False):
    """Labeled horizontal bars. Every quantity is also available as text."""
    largest = (
        1
        if percent
        else max((value for _, series in groups for _, value, _, _ in series), default=1)
    )
    rows = []
    for name, series in groups:
        bars = []
        for series_name, value, count, tone in series:
            ratio = 100 * value / largest if largest else 0
            bars.append(
                f'<div class="lab-bar-row"><span>{html(series_name)}</span>'
                '<span class="lab-bar-track" aria-hidden="true">'
                f'<span class="lab-bar-fill lab-{html(tone)}" style="width:{ratio:.3f}%">'
                "</span></span>"
                f"<strong>{html(count)}</strong></div>"
            )
        rows.append(f'<div class="lab-bar-group"><h3>{html(name)}</h3>{"".join(bars)}</div>')
    axis = "<figcaption>Rate scale · 0% to 100%</figcaption>" if percent else ""
    st.html(f'<figure class="lab-chart" aria-label="{html(label)}">{"".join(rows)}{axis}</figure>')
