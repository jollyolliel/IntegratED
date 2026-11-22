"""The one source of truth for the clay components (ADR 0012).

Three layers, one folder each under templates/components/: `base/` (the
building blocks: card, button, badge, inputs...; a `<select>` is styled from the element), composed components at the
top level (built from bases, adding utilities to reach their look), and
`shell/` (the page shells and the header / footer chrome). Every component with
a clay class or an enumerated prop has a Spec: its file, the props it
constrains, what each prop value renders, and the classes only it may write.
Components read it through the `prop` and `look` env globals;
`scripts/lint_jx.py` reads it to lint every template.
Class strings here are literal and the file is in Tailwind's `content`, so the
build keeps them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from importlib.resources import files
from zipfile import ZipFile


@dataclass(frozen=True)
class Prop:
    """An enumerated prop. `looks` holds what each value renders, one table per part
    (`{"colour": {"sky": "btn-sky", ...}}`); a component reads it with the `look` env global, never
    a dict of its own. A table may leave a value out on purpose (a clickable card has no purple):
    `look` then rejects that value like an unknown one. `owned`: the looks are design-system
    classes only this component writes."""

    allowed: tuple[str, ...]
    default: str | None
    looks: Mapping[str, Mapping[str, str]] = field(default_factory=dict)
    owned: bool = False

    def __post_init__(self) -> None:
        for part, table in self.looks.items():
            stray = sorted(set(table) - set(self.allowed))
            if stray:
                raise ValueError(f"looks[{part!r}] names values the prop does not allow: {stray}")


@dataclass(frozen=True)
class Spec:
    file: str  # repo-relative
    props: dict[str, Prop] = field(default_factory=dict)
    # The clay classes it writes outside its owned looks.
    classes: frozenset[str] = frozenset()
    # lint/rules/<id>.yml: the utilities that rule bans on this component's class, on a page.
    restyle_rule: str | None = None

    @property
    def layer(self) -> str:
        """`base`, `shell` or `composed`, from the component's folder."""
        folder = self.file.removeprefix("templates/components/").rpartition("/")[0]
        return folder or "composed"

    @property
    def owned(self) -> frozenset[str]:
        """Every class only this component may write: `classes` plus the words of its owned looks."""
        return self.classes | {
            word
            for prop in self.props.values() if prop.owned
            for table in prop.looks.values()
            for value in table.values()
            for word in value.split()
        }


def _heroicon_outline_names() -> tuple[str, ...]:
    with (files("heroicons") / "heroicons.zip").open("rb") as data, ZipFile(data) as bundle:
        return tuple(sorted(
            name.removeprefix("outline/").removesuffix(".svg")
            for name in bundle.namelist()
            if name.startswith("outline/") and name.endswith(".svg")
        ))


ICON_SIZES = {
    "3": "w-3 h-3",
    "3.5": "w-3.5 h-3.5",
    "4": "w-4 h-4",
    "5": "w-5 h-5",
    "6": "w-6 h-6",
    "8": "w-8 h-8",
    "10": "w-10 h-10",
}

#: Horizontal chevrons and arrows: they point "forward"/"back", so they mirror in RTL.
ICON_FLIP_RTL = frozenset({
    "chevron-left", "chevron-right",
    "chevron-double-left", "chevron-double-right",
    "arrow-left", "arrow-right",
    "arrow-long-left", "arrow-long-right",
    "arrow-small-left", "arrow-small-right",
    "arrow-left-circle", "arrow-right-circle",
    "arrow-uturn-left", "arrow-uturn-right",
})

_TONES = ("sky", "green", "amber", "rose")

COMPONENTS: dict[str, Spec] = {
    # ── base/ ────────────────────────────────────────────────────────
    "Icon": Spec(
        file="templates/components/base/icon.jx",
        props={
            "name": Prop(_heroicon_outline_names(), None),
            "size": Prop(tuple(ICON_SIZES), "4"),
        },
        classes=frozenset({"icon-flip-rtl"}),
    ),
    "Button": Spec(
        file="templates/components/base/button.jx",
        props={
            "variant": Prop(("accent", "sky", "soft", "gray", "danger", "amber", "rose"), "accent", owned=True, looks={
                "colour": {
                    "accent": "btn-accent", "sky": "btn-sky", "soft": "btn-soft", "gray": "btn-gray",
                    "danger": "btn-danger", "amber": "btn-amber", "rose": "btn-rose",
                },
            }),
            # A flat chip has one size: btn-flat and btn-large never combine.
            "size": Prop(("md", "lg"), "md", owned=True, looks={
                "solid": {"md": "", "lg": "btn-large"},
                "flat": {"md": ""},
            }),
        },
        classes=frozenset({"btn-clay", "btn-flat"}),
        restyle_rule="no-restyle-button",
    ),
    "Card": Spec(
        file="templates/components/base/card.jx",
        props={
            # A clickable card has no purple or pink.
            "tone": Prop((*_TONES, "purple", "pink"), "sky", owned=True, looks={
                "static": {
                    "sky": "clay-card", "green": "clay-card-green", "amber": "clay-card-amber",
                    "purple": "clay-card-purple", "pink": "clay-card-pink", "rose": "clay-card-rose",
                },
                "clickable": {
                    "sky": "quick-action-card", "green": "quick-action-card-green",
                    "amber": "quick-action-card-amber", "rose": "quick-action-card-rose",
                },
            }),
            "tag": Prop(("div", "section", "article", "aside"), "div"),
        },
        restyle_rule="no-restyle-card",
    ),
    "Badge": Spec(
        file="templates/components/base/badge.jx",
        props={
            "tone": Prop(("sky", "green", "amber", "red"), "sky", owned=True, looks={
                "badge": {"sky": "clay-badge", "green": "clay-badge-green", "amber": "clay-badge-amber", "red": "clay-badge-red"},
            }),
            "tag": Prop(("span", "div"), "span"),
        },
    ),
    "Input": Spec(
        file="templates/components/base/input.jx",
        props={
            "type": Prop(("text", "email", "password", "number", "date", "time", "search", "tel", "url"), "text"),
            "size": Prop(("md", "lg"), "md", owned=True, looks={"field": {"md": "", "lg": "clay-input-lg"}}),
        },
        classes=frozenset({"clay-input", "password-field", "password-toggle"}),
        restyle_rule="no-restyle-input",
    ),
    "Textarea": Spec(
        file="templates/components/base/textarea.jx",
        classes=frozenset({"clay-textarea"}),
        restyle_rule="no-restyle-input",
    ),
    "Choice": Spec(
        file="templates/components/base/choice.jx",
        props={"type": Prop(("checkbox", "radio"), "checkbox")},
        classes=frozenset({"choice-label", "choice-text"}),
    ),
    "Field": Spec(file="templates/components/base/field.jx", classes=frozenset({"error-msg"})),
    "Table": Spec(file="templates/components/base/table.jx", classes=frozenset({"clay-table-wrap", "clay-table"})),
    "ProgressBar": Spec(
        file="templates/components/base/progress_bar.jx",
        props={
            "tone": Prop(("sky", "green", "amber"), "sky", looks={
                "track": {"sky": "bg-primary-soft", "green": "bg-green-100", "amber": "bg-amber-100"},
                "fill": {"sky": "bg-sky-500", "green": "bg-green-500", "amber": "bg-amber-500"},
            }),
            "size": Prop(("xs", "sm", "md"), "md", looks={"height": {"xs": "h-1.5", "sm": "h-2", "md": "h-3"}}),
        },
    ),
    # ── composed ─────────────────────────────────────────────────────
    "IconBox": Spec(
        file="templates/components/icon_box.jx",
        props={
            "tone": Prop((*_TONES, "purple", "pink"), "sky", looks={
                "box": {
                    "sky": "bg-sky-50 border-card-sky-border text-primary",
                    "green": "bg-green-50 border-card-green-border text-accent",
                    "amber": "bg-amber-50 border-card-amber-border text-amber-600",
                    "rose": "bg-rose-50 border-card-rose-border text-rose-600",
                    "purple": "bg-purple-50 border-card-purple-border text-purple-600",
                    "pink": "bg-pink-50 border-card-pink-border text-pink-600",
                },
            }),
            "size": Prop(("sm", "md", "lg", "xl"), "md", looks={
                "box": {"sm": "w-9 h-9 rounded-xl", "md": "w-10 h-10 rounded-xl", "lg": "w-12 h-12 rounded-xl", "xl": "w-16 h-16 rounded-2xl"},
                "icon_size": {"sm": "4", "md": "5", "lg": "6", "xl": "8"},
            }),
        },
    ),
    "StatTile": Spec(
        file="templates/components/stat_tile.jx",
        props={"tone": Prop(_TONES, "sky", looks={
            "value": {"sky": "text-primary", "green": "text-accent", "amber": "text-amber-600", "rose": "text-rose-600"},
        })},
    ),
    "QuickAction": Spec(
        file="templates/components/quick_action.jx",
        props={
            "tone": Prop(_TONES, "sky", looks={
                "title": {"sky": "text-sky-900", "green": "text-green-900", "amber": "text-amber-900", "rose": "text-rose-900"},
                "accent": {"sky": "text-primary", "green": "text-accent", "amber": "text-amber-600", "rose": "text-rose-600"},
            }),
            "layout": Prop(("stack", "row"), "stack"),
        },
    ),
    "SectionBadge": Spec(
        file="templates/components/section_badge.jx",
        props={"tone": Prop(("sky", "amber"), "sky"), "tag": Prop(("span", "div"), "span")},
    ),
    "CountPill": Spec(file="templates/components/count_pill.jx", props={"tone": Prop(("sky", "green", "amber"), "sky")}),
    "StatusPill": Spec(
        file="templates/components/status_pill.jx",
        props={"status": Prop(("matched", "unmatched"), "unmatched", looks={
            "tone": {"matched": "green", "unmatched": "amber"},
            "dot": {"matched": "bg-green-500", "unmatched": "bg-yellow-400"},
        })},
    ),
    "FileTypeBadge": Spec(
        file="templates/components/file_type_badge.jx",
        props={"type": Prop(("pdf", "md"), "md", looks={
            "tone": {"pdf": "red", "md": "sky"},
            "text": {"pdf": "", "md": "text-sky-700"},
        })},
    ),
    "MatchScoreChip": Spec(
        file="templates/components/match_score_chip.jx",
        props={"band": Prop(("strong", "good", "fair", "weak"), None)},
    ),
    "TopicCard": Spec(
        file="templates/components/topic_card.jx",
        props={"state": Prop(("empty", "in_progress", "completed", "recommended"), "empty", looks={
            "card": {
                "empty": "", "in_progress": "topic-card-in-progress",
                "completed": "topic-card-completed", "recommended": "topic-card-recommended",
            },
            "icon": {
                "empty": "topic-icon-default", "in_progress": "topic-icon-default",
                "completed": "topic-icon-completed", "recommended": "topic-icon-default",
            },
        })},
    ),
    "EmptyState": Spec(file="templates/components/empty_state.jx", classes=frozenset({"empty-state"})),
    "GoogleButton": Spec(file="templates/components/google_button.jx", classes=frozenset({"btn-google"})),
    "LangButton": Spec(file="templates/components/lang_button.jx", classes=frozenset({"btn-lang"})),
    "AudioButton": Spec(
        file="templates/components/audio_button.jx",
        props={
            "size": Prop(("md", "lg"), "md", owned=True, looks={
                "btn": {"md": "", "lg": "audio-play-btn-lg"},
            }),
        },
        classes=frozenset({"audio-play-btn"}),
    ),
    "StepIndicator": Spec(
        file="templates/components/step_indicator.jx",
        classes=frozenset({"step-indicator", "step-item", "step-dot", "step-name", "step-done", "step-current"}),
    ),
    "JourneyScene": Spec(
        file="templates/components/journey_scene.jx",
        props={"name": Prop(("quiz",), "quiz")},
        classes=frozenset({"journey-scene", "jsc-twinkle", "jsc-pop", "jsc-route", "jsc-ripple", "jsc-pin", "jsc-magnifier"}),
    ),
    "JourneyLoader": Spec(
        file="templates/components/journey_loader.jx",
        classes=frozenset({
            "journey-loader", "is-working", "is-done", "is-leaving", "journey-panel", "journey-stage", "journey-art", "journey-status", "journey-title",
            "journey-sub", "journey-track", "journey-stop", "journey-done", "journey-just", "journey-current", "journey-upcoming",
            "journey-link", "journey-link-fill", "journey-dot", "journey-num", "journey-tick", "journey-name",
        }),
    ),
    "FormHeading": Spec(file="templates/components/form_heading.jx", classes=frozenset({"section-heading"})),
    "LanguageRow": Spec(
        file="templates/components/language_row.jx",
        classes=frozenset({"lang-row", "lang-check", "lang-level-group", "lang-level-label"}),
    ),
    "BackLink": Spec(file="templates/components/back_link.jx", classes=frozenset({"back-link"})),
    "Pagination": Spec(
        file="templates/components/pagination.jx",
        classes=frozenset({"clay-pagination", "pagination-link", "pagination-ellipsis"}),
    ),
    "PageHeader": Spec(
        file="templates/components/page_header.jx",
        props={"badge_tone": Prop(("sky", "amber"), "sky")},
        classes=frozenset({"page-header-box"}),
    ),
    "SectionTitle": Spec(
        file="templates/components/section_title.jx",
        props={"tone": Prop(("sky", "green", "amber"), "sky")},
        classes=frozenset({"section-title"}),
    ),
    "WorksheetViewer": Spec(
        file="templates/components/worksheet_viewer.jx",
        props={"file_type": Prop(("pdf", "md"), "md")},
        classes=frozenset({"preview-topbar", "preview-topbar-label"}),
    ),
    "WorksheetProse": Spec(
        file="templates/components/worksheet_prose.jx",
        props={"tag": Prop(("div", "article"), "div")},
        classes=frozenset({"worksheet-prose"}),
    ),
    "WorksheetMeta": Spec(file="templates/components/worksheet_meta.jx", classes=frozenset({"meta-label", "meta-value"})),
    "FeatureAnnouncement": Spec(
        file="templates/components/feature_announcement.jx",
        classes=frozenset({
            "announce-overlay", "announce-card", "announce-card-narrow", "announce-card-wide", "announce-close",
            "announce-body", "announce-split", "announce-media", "announce-media-top", "announce-icon",
            "announce-title", "announce-text", "announce-actions",
        }),
    ),
    "AssistantPanel": Spec(
        file="templates/components/assistant_panel.jx",
        classes=frozenset({
            "assist-panel", "assist-docked", "assist-avatar", "assist-avatar-lg", "assist-panel-header",
            "assist-panel-title", "assist-panel-sub", "assist-header-btn", "assist-tabs", "assist-tab",
            "assist-log", "assist-row", "assist-row-bot", "assist-row-user", "assist-msg", "assist-msg-user",
            "assist-msg-bot", "assist-md-scroll", "assist-live", "assist-typing", "assist-typing-label",
            "assist-typing-dots", "assist-typing-dot", "assist-change-card", "assist-change-summary",
            "assist-change-row", "assist-change-label", "assist-change-before", "assist-status-toggle",
            "assist-status-btn", "assist-change-actions", "assist-change-stale", "assist-savebar",
            "assist-composer", "assist-inputwrap", "assist-input", "assist-send", "assist-empty",
            "assist-empty-title", "assist-suggestion", "assist-history", "assist-history-item",
            "assist-history-date", "assist-history-title", "assist-history-preview",
        }),
    ),
    # ── shell/ ───────────────────────────────────────────────────────
    "Main": Spec(
        file="templates/components/shell/main.jx",
        props={
            "layout": Prop(("contained", "centered"), "contained"),
            "width": Prop(("full", "md", "lg", "2xl", "3xl", "4xl", "5xl", "7xl"), "full", looks={"max": {
                "full": "", "md": "max-w-md", "lg": "max-w-lg", "2xl": "max-w-2xl", "3xl": "max-w-3xl",
                "4xl": "max-w-4xl", "5xl": "max-w-5xl", "7xl": "max-w-7xl",
            }}),
        },
    ),
    "NavLink": Spec(
        file="templates/components/shell/nav_link.jx",
        props={"variant": Prop(("bar", "menu"), "bar")},
        classes=frozenset({"nav-link-active", "nav-link-inactive", "learn-pulse-dot"}),
    ),
    "NavButton": Spec(
        file="templates/components/shell/nav_button.jx",
        props={"variant": Prop(("register", "login", "logout"), "login", owned=True, looks={
            "button": {"register": "btn-nav-register", "login": "btn-nav-login", "logout": "btn-nav-logout"},
        })},
        classes=frozenset({"btn-nav-icon"}),
    ),
    "Header": Spec(
        file="templates/components/shell/header.jx",
        classes=frozenset({
            "logo-group", "logo-icon", "nav-logo-font", "mobile-menu", "nav-more-btn", "nav-more-menu",
            # The confirm modal (window.confirmDelete).
            "confirm-modal-overlay", "confirm-modal-icon", "confirm-modal-message",
            "confirm-modal-checkbox-row", "confirm-modal-actions",
            # Toasts, built by the header's script (window.showToast).
            "glass-notification", "glass-notification-success", "glass-notification-error",
            "glass-notification-warning", "glass-notification-info", "toast-animate-in", "toast-animate-out",
            "toast-icon-circle", "toast-icon-circle-success", "toast-icon-circle-error",
            "toast-icon-circle-warning", "toast-icon-circle-info", "toast-close-btn",
        }),
    ),
}

#: The bases every other component builds on.
BASES: dict[str, Spec] = {name: spec for name, spec in COMPONENTS.items() if spec.layer == "base"}

#: Global classes any template may write: the display typeface for a non-heading (headings get it
#: from base.css) and the clay scrollbar for a scroll container.
FREE_CLASSES = frozenset({"display-font", "clay-scroll"})

__all__ = [
    "BASES", "COMPONENTS", "FREE_CLASSES", "ICON_FLIP_RTL", "ICON_SIZES", "Prop", "Spec",
]
