"""
Gemini-assisted translation fixer for IntegratED templates.

Finds, in .jx and HTML/Jinja2 templates:
  1. Hardcoded text not wrapped in {{ t('...') }} — element text, and in .jx files
     quoted text props (label="Back") and bare text inside component tags
  2. t('key') calls where the key is missing from translations/en.json

Then uses Gemini to:
  - Suggest contextually-correct translation keys
  - Generate English values with intent comments
  - Translate en → all 11 other languages with full context

To only list hard-coded text, offline and with a suggested key for each, run
--report; for keys missing from en.json, scripts/sync_keys.py --audit.

Usage (a template path is relative to templates/ or to the repo):
    uv run scripts/translation_audit.py --report
    uv run scripts/translation_audit.py --fix templates/pages/teacher/people.jx
    uv run scripts/translation_audit.py --fix-all
    uv run scripts/translation_audit.py --translate-only
"""

import argparse
import html as html_module
import json
import re
import sys
import textwrap
import time
from copy import deepcopy
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    sys.exit("requests not installed — run: pip install requests")

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.jx_i18n import JxText, replacement, scan_jx, translatable_templates
from scripts.translation_keys import flatten_keys, get_nested, set_nested

TEMPLATES_DIR = PROJECT_ROOT / "templates"
TRANSLATIONS_DIR = PROJECT_ROOT / "translations"

import os

GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.1-flash-lite"
GEMINI_URL = (
    f"https://generativelanguage.googleapis.com/v1beta/models/"
    f"{GEMINI_MODEL}:generateContent?key={GEMINI_API_KEY}"
)

# All non-English languages
LANGUAGES = ["ar", "tr", "es", "fr", "uk", "fa", "ps", "so", "rhg", "ti", "sw"]

LANGUAGE_NAMES = {
    "ar": "Arabic",
    "tr": "Turkish",
    "es": "Spanish",
    "fr": "French",
    "uk": "Ukrainian",
    "fa": "Dari/Farsi (Afghan Persian)",
    "ps": "Pashto",
    "so": "Somali",
    "rhg": "Rohingya",
    "ti": "Tigrinya",
    "sw": "Swahili",
}

# Elements whose direct text content should be translated
TEXT_ELEMENTS = {
    "h1", "h2", "h3", "h4", "h5", "h6",
    "p", "button", "a", "label", "span",
    "li", "th", "td", "title",
    "strong", "em", "small", "dt", "dd",
    "caption", "legend", "option",
}

# Attributes whose values are read aloud or shown, so need translating like element text
TEXT_ATTRS = ("placeholder", "alt", "title", "aria-label")
# attr="value" or attr='value' (not the tail of data-x-title)
ATTR_RE = re.compile(
    r'(?<![\w-])(?P<attr>' + "|".join(TEXT_ATTRS) + r')\s*=\s*(?:"(?P<dq>[^"]*)"|\'(?P<sq>[^\']*)\')',
    re.IGNORECASE,
)

# The inside of an HTML start tag: Jinja in an attribute may hold a `>` (class="{% if n > 0 %}…")
TAG_ATTRS = r"(?:\{\{(?:(?!\}\}).)*\}\}|\{%(?:(?!%\}).)*%\}|[^>{]|\{(?![{%]))*"

# Text to skip: brand names, numbers, single symbols, etc.
SKIP_TEXT_RE = re.compile(
    r"^[\s\d\W]*$"                              # only whitespace/numbers/symbols
    r"|^IntegratED$"
    r"|^ACS\s*Athens$"
    r"|^The\s+Home\s+Project$"
    r"|^Google$"
    r"|^[©®™€$£%\-\+\/\|\.,:;!?\(\)\[\]{}]+$",
    re.IGNORECASE,
)

# Platform context injected into every Gemini prompt
PLATFORM_CONTEXT = textwrap.dedent("""
    === PLATFORM CONTEXT ===
    IntegratED is a Youth-to-Youth (Y2Y) learning platform at ACS Athens, Greece.
    It pairs ACS student volunteers with refugees from The Home Project who are
    largely illiterate in any language (Arabic, Dari, Pashto, Somali, Rohingya, Tigrinya, Swahili, etc.).

    App sections:
    - Learner: adaptive quizzes, word-storm, map placement test, Rocket Launch game, XP/levels/avatar
    - Volunteer: paired-learner management, worksheets, resources
    - Teacher: volunteer-learner pair management, attendance, worksheets
    - School Admin / Administrator: dashboards, donations, user management

    Target audience: refugees aged 15–25 with limited literacy.
    Language must be SIMPLE, CLEAR, ENCOURAGING. Never patronising.
    The platform supports 12 languages. RTL: Arabic, Dari/Farsi, Pashto.
    === END CONTEXT ===
""").strip()


# ---------------------------------------------------------------------------
# Translation file helpers
# ---------------------------------------------------------------------------

def load_translations() -> dict[str, dict]:
    """Load all translation JSON files. Returns {lang_code: nested_dict}."""
    result = {}
    for path in TRANSLATIONS_DIR.glob("*.json"):
        lang = path.stem
        with open(path, encoding="utf-8") as f:
            result[lang] = json.load(f)
    return result


def save_translation(lang: str, data: dict) -> None:
    path = TRANSLATIONS_DIR / f"{lang}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"  [ok] Saved {path.name}")


# ---------------------------------------------------------------------------
# Template scanning
# ---------------------------------------------------------------------------

def _strip_jinja(content: str) -> str:
    """Replace Jinja expressions/blocks with placeholders for text scanning."""
    # Replace block tags ({% ... %})
    content = re.sub(r"\{%-?\s.*?-?%\}", " ", content, flags=re.DOTALL)
    # Replace variable expressions ({{ ... }}) with a marker
    content = re.sub(r"\{\{.*?\}\}", "__JINJA__", content, flags=re.DOTALL)
    return content


def _decode_html_entities(text: str) -> str:
    return html_module.unescape(text)


def find_t_calls(content: str) -> list[str]:
    """Find all t('key') keys used in a template."""
    return re.findall(r"\{\{\s*t\(['\"]([^'\"]+)['\"]\s*(?:,.*?)?\)", content)


def _context_lines(lines: list[str], line_no: int, window: int = 3) -> str:
    """Lines around 0-based `line_no`, numbered from 1."""
    start = max(0, line_no - window)
    end = min(len(lines), line_no + window + 1)
    return "\n".join(f"{i+1:4d}│ {lines[i]}" for i in range(start, end))


def _jx_issue(item: JxText, source: str) -> dict:
    """A hardcoded-text issue for a jx prop or component text. `span` lets --fix patch it in place."""
    return {
        "type": "hardcoded_text",
        "text": item.text,
        "element_tag": f"{item.tag} {item.prop}=" if item.prop else item.tag,
        "line_no": item.line,
        "context_lines": _context_lines(source.split("\n"), item.line - 1),
        "original_snippet": source[item.start:item.end],
        "span": (item.start, item.end),
        "jx": item,
    }


def find_hardcoded_texts(content: str, template_path: Path, source: str | None = None) -> list[dict]:
    """
    Find text nodes inside HTML elements that are NOT already wrapped in t().
    `source` is the file as written, for context lines, when `content` is jx markup.
    Returns list of dicts: {text, element_tag, line_no, context_lines, original_snippet}
    """
    issues: list[dict[str, Any]] = []
    lines = content.split("\n")
    source_lines = (source if source is not None else content).split("\n")

    # Build a line-numbered version for context extraction
    def get_context(line_no: int, window: int = 3) -> str:
        return _context_lines(source_lines, line_no, window)

    # --- Strategy 1: single-line element text ---
    # Match: <tag ...>TEXT</tag> where TEXT has no nested tags and no t() call
    single_re = re.compile(
        r"<(" + "|".join(TEXT_ELEMENTS) + r")(\s" + TAG_ATTRS + r")?>([^<\n]+)</\1>",
        re.IGNORECASE,
    )
    for line_no, line in enumerate(lines):
        for m in single_re.finditer(line):
            tag = m.group(1).lower()
            inner = m.group(3)
            # Skip if it's purely Jinja
            stripped_inner = re.sub(r"\{\{.*?\}\}", "", inner, flags=re.DOTALL)
            stripped_inner = re.sub(r"\{%.*?%\}", "", stripped_inner, flags=re.DOTALL)
            text = _decode_html_entities(stripped_inner).strip()
            if not text:
                continue
            if SKIP_TEXT_RE.match(text):
                continue
            # Skip if contains only jinja placeholders
            if "__JINJA__" in text and len(text.replace("__JINJA__", "").strip()) == 0:
                continue
            # Skip if original already has a t() call and no extra text
            if "t(" in inner and not stripped_inner.strip():
                continue
            issues.append({
                "type": "hardcoded_text",
                "text": text,
                "element_tag": tag,
                "line_no": line_no + 1,
                "context_lines": get_context(line_no),
                "original_snippet": m.group(0),
            })

    # --- Strategy 2: multi-line button/element text ---
    # Buttons often span multiple lines: <button ...>\n   Text\n</button>
    multi_re = re.compile(
        r"<(button|a)(\s" + TAG_ATTRS + r")?\s*>\s*\n([\s\S]*?)\n\s*</(button|a)>",
        re.IGNORECASE,
    )
    for m in multi_re.finditer(content):
        tag = m.group(1).lower()
        inner = m.group(3)
        # Check if inner has any hardcoded text (not in Jinja)
        stripped_inner = re.sub(r"\{\{.*?\}\}", "", inner, flags=re.DOTALL)
        stripped_inner = re.sub(r"\{%.*?%\}", "", stripped_inner, flags=re.DOTALL)
        # Remove HTML tags inside
        stripped_inner = re.sub(r"<[^>]+>", " ", stripped_inner)
        text = _decode_html_entities(stripped_inner).strip()
        if not text:
            continue
        if SKIP_TEXT_RE.match(text):
            continue
        # Find line number of the start
        start_line = content[: m.start()].count("\n")
        # Avoid duplicate with single-line scanner
        already_found = any(
            i["original_snippet"] in m.group(0)
            for i in issues
        )
        if already_found:
            continue
        issues.append({
            "type": "hardcoded_text",
            "text": text,
            "element_tag": tag,
            "line_no": start_line + 1,
            "context_lines": get_context(start_line),
            "original_snippet": m.group(0)[:200],  # truncate for display
        })

    # --- Strategy 3: text in an attribute the learner hears or sees (placeholder, alt, ...) ---
    for m in ATTR_RE.finditer(content):
        value = m.group("dq") if m.group("dq") is not None else m.group("sq")
        if not value or "t(" in value:
            continue
        text = _decode_html_entities(_strip_jinja(value)).strip()
        if not text or SKIP_TEXT_RE.match(text):
            continue
        line_no = content[: m.start()].count("\n")
        issues.append({
            "type": "hardcoded_text",
            "text": text,
            "element_tag": "@" + m.group("attr").lower(),
            "line_no": line_no + 1,
            "context_lines": get_context(line_no),
            "original_snippet": m.group(0),
        })

    # Deduplicate by text
    seen = set()
    unique = []
    for issue in issues:
        key = issue["text"][:80]
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


def scan_template(path: Path, en_flat: dict[str, str]) -> dict:
    """Scan one template: {"hardcoded": text issues, "missing_keys": t() keys absent from en.json}."""
    content = path.read_text(encoding="utf-8")

    # Missing keys in en.json
    t_keys = find_t_calls(content)
    missing_keys = [k for k in t_keys if k not in en_flat]

    # Hardcoded text
    if path.suffix == ".jx":
        markup, jx_items = scan_jx(content, str(path.relative_to(TEMPLATES_DIR)))
        hardcoded = find_hardcoded_texts(markup, path, source=content)
        hardcoded += [_jx_issue(item, content) for item in jx_items if not SKIP_TEXT_RE.match(item.text)]
    else:
        hardcoded = find_hardcoded_texts(content, path)

    return {
        "hardcoded": hardcoded,
        "missing_keys": missing_keys,
    }


# ---------------------------------------------------------------------------
# Offline report: every template's hard-coded text, with a suggested key
# ---------------------------------------------------------------------------

def infer_section(rel_path: Path) -> str:
    """The translation section a template's keys belong in.

    Args:
        rel_path (Path): Template path relative to `templates/`.

    Returns:
        str: The role folder under `pages/` or `page_components/` (pages/learner/dashboard.jx →
            "learner"), "components" for a shared component, else the file name without extension.
    """
    parts = rel_path.parts
    if parts[0] == "components":
        return "components"
    if parts[0] in ("pages", "page_components"):
        parts = parts[1:]
    return Path(parts[0]).stem if len(parts) == 1 else parts[0]


def suggested_key(section: str, text: str) -> str:
    """`<section>.<snake_case slug of text>` (at most 40 characters of slug; `text` when empty)."""
    slug = re.sub(r"\s+", "_", re.sub(r"[^\w\s]", "", text.strip().lower()))
    slug = re.sub(r"_+", "_", slug).strip("_")[:40]
    return f"{section}.{slug or 'text'}"


def report_findings(path: Path) -> list[tuple[int, str, str, str]]:
    """One template's hard-coded text as `(line, element, text, suggested key)`, by line.

    Args:
        path (Path): A template under `TEMPLATES_DIR`.

    Returns:
        list[tuple[int, str, str, str]]: What `--report` prints for it.
    """
    section = infer_section(path.relative_to(TEMPLATES_DIR))
    found = []
    for issue in scan_template(path, {})["hardcoded"]:
        tag = issue["element_tag"]
        item = issue.get("jx")
        element = (f"<{item.tag}>@{item.prop}" if item.prop else f"<{item.tag}>") if item else (
            tag if tag.startswith("@") else f"<{tag}>")
        found.append((issue["line_no"], element, issue["text"][:80], suggested_key(section, issue["text"])))
    return sorted(found, key=lambda finding: finding[0])


def cmd_report() -> None:
    """Print every template's hard-coded text and the suggested keys as JSON. Needs no API key."""
    paths = translatable_templates()
    findings = {path: report_findings(path) for path in paths}
    findings = {path: found for path, found in findings.items() if found}
    print("=== i18n report ===")
    print(f"Templates scanned : {len(paths)}")
    print(f"Files with issues : {len(findings)}")
    print(f"Total findings    : {sum(len(found) for found in findings.values())}\n")
    new_keys: dict[str, str] = {}
    for path, found in findings.items():
        print(f"--- {path.relative_to(TEMPLATES_DIR)} ({len(found)}) ---")
        for line_no, element, text, key in found:
            print(f"  L{line_no:4d}  {element:<20}  {text!r:<60}  -> {key}")
            new_keys.setdefault(key, text)
        print()
    print("=== Suggested keys ===")
    print(json.dumps(dict(sorted(new_keys.items())), indent=2, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Gemini helpers
# ---------------------------------------------------------------------------

def gemini_call(prompt: str, *, json_mode: bool = True, temperature: float = 0.2) -> str:
    """Call Gemini and return the text response. Retries on 429."""
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": temperature,
            "responseMimeType": "application/json" if json_mode else "text/plain",
        },
    }
    for attempt in range(4):
        resp = requests.post(GEMINI_URL, json=payload, timeout=120)
        if resp.status_code == 429:
            wait = 20 * (attempt + 1)
            print(f"  Rate-limited — waiting {wait}s…")
            time.sleep(wait)
            continue
        if resp.status_code != 200:
            raise RuntimeError(f"Gemini error {resp.status_code}: {resp.text[:500]}")
        data = resp.json()
        return data["candidates"][0]["content"]["parts"][0]["text"]
    raise RuntimeError("Gemini rate limit exceeded after retries")


# ---------------------------------------------------------------------------
# Phase 2: Key generation (hardcoded text → translation keys + EN values)
# ---------------------------------------------------------------------------

def _template_role(rel_path: str) -> str:
    """Derive a human-readable role description from template path."""
    # First match wins: specific files before the folders that hold them
    mapping = {
        "/components/shell/header.jx": "Global site header / navigation",
        "/components/shell/footer.jx": "Global site footer",
        "/components/shell/": "Page shell shared by every page (layout, game and legal frames)",
        "/components/": "Shared UI component",  # the leading / keeps page_components/ out
        "learner/": "Learner-facing dashboard and learning features",
        "volunteer/": "Volunteer-facing dashboard and partner management",
        "teacher/": "Teacher portal for managing pairs, attendance, worksheets",
        "school_admin/": "School administrator dashboard",
        "administrator/": "Platform administrator dashboard",
        "legal/": "Legal pages (terms, privacy)",
        "page_components/public/": "Public site sections (schools, articles, donations)",
        "pages/login.jx": "Login page",
        "pages/register.jx": "Registration / sign-up page",
        "pages/index.jx": "Public landing / home page",
        "pages/about.jx": "About page",
        "pages/donations.jx": "Donations page",
        "pages/donation_success.jx": "Donation thank-you page",
        "pages/schools.jx": "Schools overview page",
        "pages/school_detail.jx": "One school's public page",
        "pages/articles.jx": "Articles list page",
        "pages/article_detail.jx": "One article's page",
        "pages/settings.jx": "User settings page",
        "pages/error.jx": "Error page",
        "starting_up.html": "Holding page shown while the app starts",
    }
    rel_path = "/" + rel_path.replace("\\", "/")
    for pattern, desc in mapping.items():
        if pattern in rel_path:
            return desc
    return f"Page: {rel_path}"


def generate_keys_for_template(
    template_path: Path,
    issues: list[dict],
    en_flat: dict[str, str],
) -> list[dict]:
    """
    Ask Gemini to assign translation keys and English values for each hardcoded text.
    Returns list of: {original_snippet, text, key, en_value, intent_comment}
    """
    if not issues:
        return []

    rel_path = str(template_path.relative_to(TEMPLATES_DIR))
    template_content = template_path.read_text(encoding="utf-8")

    # Build existing key list for consistency (first 200 keys max to save tokens)
    existing_keys_sample = list(en_flat.keys())[:200]
    existing_keys_str = "\n".join(existing_keys_sample)

    # Build the items list for the prompt
    items_str = ""
    for i, issue in enumerate(issues):
        items_str += f"\n[{i}]\n"
        items_str += f'  text: "{issue["text"]}"\n'
        items_str += f"  element: <{issue['element_tag']}>\n"
        items_str += "  context:\n"
        for ctx_line in issue["context_lines"].split("\n"):
            items_str += f"    {ctx_line}\n"

    prompt = f"""
{PLATFORM_CONTEXT}

You are assigning i18n translation keys to hardcoded English text found in an HTML/Jinja2 template.

TEMPLATE: {rel_path}
TEMPLATE ROLE: {_template_role(rel_path)}

FULL TEMPLATE (for context):
```html
{template_content[:6000]}
```

EXISTING TRANSLATION KEYS (follow this naming convention exactly):
{existing_keys_str}

HARDCODED TEXTS TO ASSIGN KEYS:
{items_str}

RULES:
1. Keys use dot notation: <section>.<sub_section>.<name>  e.g. "teacher.people.auto_match_btn"
2. Section should match the page area: teacher, learner, volunteer, school_admin, admin, auth, nav, common, etc.
3. If a key for this exact concept already exists in the existing keys list — REUSE it.
4. Values must be the clean English text (no HTML, no Jinja).
5. intent_comment: ONE short sentence explaining what this UI element does and the exact nuance/context.
   This comment helps future translators know if e.g. "Save" means save-a-file vs save-a-person.
6. For multi-word button labels like "Auto-Match Pairs", keep them natural (don't over-shorten).
7. Never create keys inside "integrated" namespace.

Respond with a JSON array, one object per input item (preserve index order):
[
  {{
    "index": 0,
    "key": "teacher.people.auto_match_btn",
    "en_value": "Auto-Match Pairs",
    "intent_comment": "Button that triggers automatic volunteer-learner pairing algorithm."
  }},
  ...
]
"""

    raw = gemini_call(prompt)
    try:
        # Strip markdown fences if present
        cleaned = re.sub(r"^```(?:json)?\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```$", "", cleaned.strip())
        assignments = json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"  Warning: Gemini returned invalid JSON — {e}")
        print(f"  Raw response: {raw[:500]}")
        return []

    result = []
    for a in assignments:
        idx = a.get("index", 0)
        if idx < len(issues):
            result.append({
                **issues[idx],
                "key": a["key"],
                "en_value": a["en_value"],
                "intent_comment": a.get("intent_comment", ""),
            })
    return result


# ---------------------------------------------------------------------------
# Phase 3: Template patching
# ---------------------------------------------------------------------------

def _make_t_replacement(original_snippet: str, key: str, element_tag: str) -> tuple[str, str]:
    """
    Given the original HTML snippet and proposed key, produce the replacement snippet.
    Returns (old_text, new_text) for str.replace().
    """
    # For single-line: <tag attrs>TEXT</tag>  →  <tag attrs>{{ t('key') }}</tag>
    # We need to replace only the inner text portion.
    jinja_call = "{{ t('" + key + "') }}"

    # Find the inner text: between > and </tag>
    inner_re = re.compile(
        r"(<" + re.escape(element_tag) + r"\b" + TAG_ATTRS + r">)(.*?)(</" + re.escape(element_tag) + r">)",
        re.IGNORECASE | re.DOTALL,
    )
    m = inner_re.search(original_snippet)
    if m:
        new_snippet = m.group(1) + jinja_call + m.group(3)
        return original_snippet, new_snippet
    # Fallback: replace inner text naively
    return original_snippet, original_snippet


def apply_template_patches(template_path: Path, replacements: list[dict]) -> int:
    """
    Patch a template file in-place. Returns number of replacements applied.
    """
    content = template_path.read_text(encoding="utf-8")
    count = 0

    # jx props and component text carry their exact span: patch those first, last span first,
    # so the offsets still hold; the string-matched HTML patches below don't need offsets
    in_place = sorted((r for r in replacements if "span" in r), key=lambda r: r["span"][0], reverse=True)
    for r in in_place:
        start, end = r["span"]
        if content[start:end] != r["original_snippet"]:
            print(f"  Warning: line {r['line_no']} changed since the scan — not patched")
            continue
        content = content[:start] + replacement(r["jx"], r["key"]) + content[end:]
        count += 1

    for r in replacements:
        if "span" in r:
            continue
        original = r["original_snippet"]
        key = r["key"]
        tag = r["element_tag"]

        old, new = _make_t_replacement(original, key, tag)
        if old in content and old != new:
            content = content.replace(old, new, 1)
            count += 1
        else:
            # Try matching just the text portion (helpful for multi-line buttons)
            text = r["text"]
            if text and text in content:
                content = content.replace(text, "{{ t('" + key + "') }}", 1)
                count += 1

    template_path.write_text(content, encoding="utf-8")
    return count


# ---------------------------------------------------------------------------
# Phase 4: Update en.json
# ---------------------------------------------------------------------------

def update_en_json(replacements: list[dict], en_data: dict) -> dict:
    """Add new keys to en.json data. Returns updated data."""
    updated = deepcopy(en_data)
    for r in replacements:
        key = r["key"]
        val = r["en_value"]
        comment = r.get("intent_comment", "")
        # Only add if not already present
        if get_nested(updated, key) is None:
            set_nested(updated, key, val)
            if comment:
                # Store intent comments in a parallel __comments__ sub-object
                key + ".__comment__"
                # We'll handle comments separately — store in en_comments.json
    return updated


def save_intent_comments(replacements: list[dict]) -> None:
    """Append intent comments to scripts/translation_comments.json for reference."""
    comments_path = PROJECT_ROOT / "scripts" / "translation_comments.json"
    if comments_path.exists():
        with open(comments_path, encoding="utf-8") as f:
            existing = json.load(f)
    else:
        existing = {}

    for r in replacements:
        key = r["key"]
        comment = r.get("intent_comment", "")
        if comment and key not in existing:
            existing[key] = comment

    with open(comments_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------------------
# Phase 5: Translate to all languages
# ---------------------------------------------------------------------------

def translate_to_language(
    lang: str,
    new_keys: dict[str, str],   # {key: en_value}
    intent_comments: dict[str, str],  # {key: comment}
    existing_lang_data: dict,   # existing translations for this lang
    existing_en_flat: dict[str, str],  # all en.json keys for context
) -> dict[str, str]:
    """
    Translate new_keys from English to target language.
    Returns {key: translated_value}.
    """
    lang_name = LANGUAGE_NAMES.get(lang, lang)

    # Provide a sample of existing translations for style consistency
    existing_flat = flatten_keys(existing_lang_data)
    sample_pairs = list(existing_flat.items())[:40]
    sample_str = "\n".join(f'  "{k}": "{v}"' for k, v in sample_pairs)

    # Build items list
    items = []
    for key, en_val in new_keys.items():
        comment = intent_comments.get(key, "")
        items.append({
            "key": key,
            "en": en_val,
            "context": comment,
        })

    items_str = json.dumps(items, ensure_ascii=False, indent=2)

    prompt = f"""
{PLATFORM_CONTEXT}

You are translating UI strings for IntegratED from English into {lang_name} ({lang}).

CRITICAL AUDIENCE NOTE:
- Primary users are refugees with LIMITED LITERACY in their native language.
- Translations must use SIMPLE, EVERYDAY vocabulary. No formal or literary register.
- Short strings (buttons, labels) must be very concise — never longer than the English.
- For RTL languages (Arabic, Dari/Farsi, Pashto): do not add LTR markers.

STYLE CONSISTENCY — sample of existing {lang_name} translations:
{sample_str}

STRINGS TO TRANSLATE (each has an "en" value and optional "context" explaining intent):
{items_str}

Rules:
1. Translate the "en" value to {lang_name}, using the "context" to resolve ambiguity.
2. Keep placeholders like {{name}}, {{year}}, {{count}} exactly as-is.
3. Keep HTML entities like &amp; if present.
4. Never translate proper nouns: IntegratED, ACS Athens, The Home Project, Google.
5. Return a JSON object mapping "key" → "translated_value" only.

Response format:
{{
  "teacher.people.auto_match_btn": "...",
  ...
}}
"""

    raw = gemini_call(prompt, temperature=0.1)
    try:
        cleaned = re.sub(r"^```(?:json)?\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```$", "", cleaned.strip())
        return json.loads(cleaned)
    except json.JSONDecodeError as e:
        print(f"  Warning: bad JSON for {lang} — {e}")
        print(f"  Raw: {raw[:300]}")
        return {}


def run_translations(
    new_keys: dict[str, str],
    intent_comments: dict[str, str],
    translations: dict[str, dict],
    en_flat: dict[str, str],
) -> None:
    """Translate new_keys into all non-English languages and save."""
    if not new_keys:
        print("No new keys to translate.")
        return

    print(f"\nTranslating {len(new_keys)} new key(s) into {len(LANGUAGES)} languages…")
    for lang in LANGUAGES:
        lang_name = LANGUAGE_NAMES.get(lang, lang)
        print(f"  → {lang_name} ({lang})…", end=" ", flush=True)
        existing_lang_data = translations.get(lang, {})

        translated = translate_to_language(
            lang=lang,
            new_keys=new_keys,
            intent_comments=intent_comments,
            existing_lang_data=existing_lang_data,
            existing_en_flat=en_flat,
        )

        if not translated:
            print("skipped (no output)")
            continue

        lang_data = deepcopy(existing_lang_data)
        added = 0
        for key, val in translated.items():
            if get_nested(lang_data, key) is None:
                set_nested(lang_data, key, val)
                added += 1

        save_translation(lang, lang_data)
        print(f"added {added} key(s)")
        time.sleep(1)  # gentle rate-limit respect


# ---------------------------------------------------------------------------
# Also handle: t() calls with missing keys in en.json
# ---------------------------------------------------------------------------

def generate_en_values_for_missing_keys(
    missing_keys: list[str],
    template_path: Path,
    en_flat: dict[str, str],
) -> dict[str, str]:
    """
    For t('key') calls that exist in templates but NOT in en.json,
    ask Gemini to infer the appropriate English value from the key name + template context.
    Returns {key: en_value}.
    """
    if not missing_keys:
        return {}

    rel_path = str(template_path.relative_to(TEMPLATES_DIR))
    template_content = template_path.read_text(encoding="utf-8")

    keys_str = "\n".join(f"  - {k}" for k in missing_keys)

    prompt = f"""
{PLATFORM_CONTEXT}

Some translation keys are referenced in a template but missing from en.json.
Infer appropriate English values from the key names and template context.

TEMPLATE: {rel_path}
TEMPLATE ROLE: {_template_role(rel_path)}

TEMPLATE SNIPPET (first 4000 chars):
```html
{template_content[:4000]}
```

MISSING KEYS:
{keys_str}

For each key, return the most likely English UI string value.
Follow the naming patterns: "nav.home" → "Home", "auth.welcome_back" → "Welcome Back",
"teacher.dashboard.total_hours" → "Total Hours", etc.

Response format (JSON object):
{{
  "key.name": "English value",
  ...
}}
"""

    raw = gemini_call(prompt)
    try:
        cleaned = re.sub(r"^```(?:json)?\n?", "", raw.strip())
        cleaned = re.sub(r"\n?```$", "", cleaned.strip())
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return {}


# ---------------------------------------------------------------------------
# Main orchestration
# ---------------------------------------------------------------------------

def cmd_fix(template_path: Path) -> None:
    """Fix one template: generate keys, patch template, update en.json, translate."""
    translations = load_translations()
    en_data = translations.get("en", {})
    en_flat = flatten_keys(en_data)

    rel = template_path.relative_to(TEMPLATES_DIR)
    print(f"\nProcessing: {rel}")

    result = scan_template(template_path, en_flat)
    hardcoded = result["hardcoded"]
    missing = result["missing_keys"]

    if not hardcoded and not missing:
        print("  [ok] No issues found.")
        return

    new_keys: dict[str, str] = {}
    intent_comments: dict[str, str] = {}
    all_replacements: list[dict] = []

    # --- Handle hardcoded text ---
    if hardcoded:
        print(f"\n  Generating keys for {len(hardcoded)} hardcoded text(s)…")
        replacements = generate_keys_for_template(template_path, hardcoded, en_flat)

        if replacements:
            print("  Patching template…")
            patched = apply_template_patches(template_path, replacements)
            print(f"  [ok] Patched {patched} element(s)")

            # Reload en_flat after possible prior updates
            for r in replacements:
                if get_nested(en_data, r["key"]) is None:
                    new_keys[r["key"]] = r["en_value"]
                    if r.get("intent_comment"):
                        intent_comments[r["key"]] = r["intent_comment"]
            all_replacements.extend(replacements)

    # --- Handle missing keys ---
    if missing:
        print(f"\n  Inferring EN values for {len(missing)} missing key(s)…")
        inferred = generate_en_values_for_missing_keys(missing, template_path, en_flat)
        for key, val in inferred.items():
            if get_nested(en_data, key) is None:
                new_keys[key] = val
                set_nested(en_data, key, val)
        if inferred:
            print(f"  [ok] Inferred {len(inferred)} value(s)")

    # --- Update en.json ---
    if new_keys:
        for key, val in new_keys.items():
            set_nested(en_data, key, val)
        save_translation("en", en_data)
        save_intent_comments(all_replacements)

        # Refresh flat map
        en_flat = flatten_keys(en_data)

        # --- Translate to all languages ---
        run_translations(new_keys, intent_comments, translations, en_flat)
    else:
        print("  No new English keys added.")


def cmd_translate_only() -> None:
    """Find keys in en.json missing from other language files and translate them."""
    translations = load_translations()
    en_data = translations.get("en", {})
    en_flat = flatten_keys(en_data)

    # Load intent comments if available
    comments_path = PROJECT_ROOT / "scripts" / "translation_comments.json"
    intent_comments: dict[str, str] = {}
    if comments_path.exists():
        with open(comments_path, encoding="utf-8") as f:
            intent_comments = json.load(f)

    print(f"Checking {len(en_flat)} EN keys across {len(LANGUAGES)} languages…")

    for lang in LANGUAGES:
        lang_name = LANGUAGE_NAMES.get(lang, lang)
        lang_flat = flatten_keys(translations.get(lang, {}))
        missing = {k: v for k, v in en_flat.items() if k not in lang_flat}
        if missing:
            print(f"  {lang_name}: {len(missing)} missing key(s)")

    # Gather all keys missing from any language
    all_missing_per_lang: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        lang_flat = flatten_keys(translations.get(lang, {}))
        missing = {k: v for k, v in en_flat.items() if k not in lang_flat}
        if missing:
            all_missing_per_lang[lang] = missing

    if not all_missing_per_lang:
        print("All languages are complete!")
        return

    for lang, missing_keys in all_missing_per_lang.items():
        lang_name = LANGUAGE_NAMES.get(lang, lang)
        print(f"\n→ Translating {len(missing_keys)} missing keys into {lang_name}…")
        lang_data = deepcopy(translations.get(lang, {}))
        translated = translate_to_language(
            lang=lang,
            new_keys=missing_keys,
            intent_comments=intent_comments,
            existing_lang_data=lang_data,
            existing_en_flat=en_flat,
        )
        if not translated:
            print("  skipped (no output)")
            continue
        added = 0
        for key, val in translated.items():
            if get_nested(lang_data, key) is None:
                set_nested(lang_data, key, val)
                added += 1
        save_translation(lang, lang_data)
        print(f"  [ok] Added {added} key(s)")
        time.sleep(1)


# ---------------------------------------------------------------------------
# Language quality audit: detect English values sitting in non-English files
# ---------------------------------------------------------------------------

# Keys where identical-to-English is acceptable (brand names, abbreviations, etc.)
_ALLOW_SAME_AS_EN = re.compile(
    r"^(DB|Google|IntegratED|ACS\s*Athens|The\s+Home\s+Project"
    r"|Log\s*in|Log\s*out|[A-Z]{1,4}|[©®™]|\d.*)$",
    re.IGNORECASE,
)

# Keys whose names suggest the value should stay in English
_ALLOW_SAME_KEY_SUFFIXES = {
    "lang.en", "lang.ar", "lang.tr", "lang.es", "lang.fr",
    "lang.uk", "lang.fa", "lang.ps", "lang.so", "lang.rhg",
    "lang.ti", "lang.sw", "lang.other",
    "nav.db",  # "DB" abbreviation
}


def _is_untranslated(key: str, lang_value: str, en_value: str) -> bool:
    """Return True if lang_value looks like it was never translated (still English)."""
    if lang_value != en_value:
        return False
    if key in _ALLOW_SAME_KEY_SUFFIXES:
        return False
    if _ALLOW_SAME_AS_EN.match(lang_value.strip()):
        return False
    # Short values (≤3 chars) are often the same cross-language
    return not len(lang_value.strip()) <= 3


def cmd_audit_langs() -> None:
    """Report untranslated (English) values in every non-English language file."""
    translations = load_translations()
    en_flat = flatten_keys(translations.get("en", {}))

    grand_total = 0
    for lang in LANGUAGES:
        lang_name = LANGUAGE_NAMES.get(lang, lang)
        lang_flat = flatten_keys(translations.get(lang, {}))

        untranslated = [
            k for k, v in lang_flat.items()
            if k in en_flat and _is_untranslated(k, v, en_flat[k])
        ]
        missing = [k for k in en_flat if k not in lang_flat]

        issues = len(untranslated) + len(missing)
        grand_total += issues

        status = "[ok]" if issues == 0 else f"[!] {issues} issue(s)"
        print(f"  {lang_name:25s} ({lang})  {status}")
        if untranslated:
            print(f"    untranslated (same as EN): {len(untranslated)}")
        if missing:
            print(f"    missing keys:              {len(missing)}")

    print(f"\nTotal issues: {grand_total}")
    if grand_total:
        print("Run --fix-lang <code> to fix a specific language, e.g.: --fix-lang ti")
        print("Run --fix-lang all to fix every language at once.")


def cmd_fix_lang(lang: str) -> None:
    """
    Re-translate every value in lang.json that is still English (identical to en.json),
    plus add any keys missing from that language file.
    """
    translations = load_translations()
    en_data = translations.get("en", {})
    en_flat = flatten_keys(en_data)

    comments_path = PROJECT_ROOT / "scripts" / "translation_comments.json"
    intent_comments: dict[str, str] = {}
    if comments_path.exists():
        with open(comments_path, encoding="utf-8") as f:
            intent_comments = json.load(f)

    langs_to_fix = LANGUAGES if lang == "all" else [lang]

    for target_lang in langs_to_fix:
        if target_lang not in LANGUAGES:
            print(f"Unknown language code: {target_lang}. Valid: {', '.join(LANGUAGES)}")
            continue

        lang_name = LANGUAGE_NAMES.get(target_lang, target_lang)
        lang_data = deepcopy(translations.get(target_lang, {}))
        lang_flat = flatten_keys(lang_data)

        untranslated = {
            k: en_flat[k]
            for k, v in lang_flat.items()
            if k in en_flat and _is_untranslated(k, v, en_flat[k])
        }
        missing = {
            k: en_flat[k]
            for k in en_flat
            if k not in lang_flat
        }
        to_translate = {**untranslated, **missing}

        if not to_translate:
            print(f"  {lang_name}: nothing to fix.")
            continue

        print(f"\n  {lang_name} ({target_lang}): {len(untranslated)} untranslated + {len(missing)} missing = {len(to_translate)} to fix")

        # Translate in batches of 80 keys to stay within token limits
        BATCH = 80
        keys = list(to_translate.items())
        all_translated: dict[str, str] = {}

        for batch_start in range(0, len(keys), BATCH):
            batch = dict(keys[batch_start: batch_start + BATCH])
            batch_num = batch_start // BATCH + 1
            total_batches = (len(keys) + BATCH - 1) // BATCH
            print(f"    Batch {batch_num}/{total_batches} ({len(batch)} keys)…", end=" ", flush=True)

            translated = translate_to_language(
                lang=target_lang,
                new_keys=batch,
                intent_comments=intent_comments,
                existing_lang_data=lang_data,
                existing_en_flat=en_flat,
            )
            if translated:
                all_translated.update(translated)
                print(f"got {len(translated)} translations")
            else:
                print("no output — skipping batch")
            time.sleep(1)

        # Apply: overwrite untranslated values, add missing keys
        applied = 0
        for key, val in all_translated.items():
            set_nested(lang_data, key, val)
            applied += 1

        save_translation(target_lang, lang_data)
        print(f"  [ok] {lang_name}: applied {applied} translation(s)")
        time.sleep(2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def resolve_template(arg: str) -> Path:
    """A template path given relative to templates/ (`pages/x.jx`) or to the repo (`templates/pages/x.jx`)."""
    path = Path(arg)
    if path.is_absolute():
        return path
    from_repo = PROJECT_ROOT / path
    if path.parts[:1] == ("templates",) and from_repo.exists():
        return from_repo
    return TEMPLATES_DIR / path


def main():
    # Windows: force UTF-8 stdout so emoji/unicode in output doesn't crash
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # ty: ignore[unresolved-attribute]
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")  # ty: ignore[unresolved-attribute]


    parser = argparse.ArgumentParser(
        description="IntegratED translation audit and auto-fix tool"
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--report",
        action="store_true",
        help="Offline: list every template's hard-coded text with a suggested key (no API key needed).",
    )
    group.add_argument(
        "--fix",
        metavar="TEMPLATE",
        help="Fix one template (relative to templates/, the repo, or absolute).",
    )
    group.add_argument(
        "--fix-all",
        action="store_true",
        help="Fix all templates one by one.",
    )
    group.add_argument(
        "--translate-only",
        action="store_true",
        help="Only run missing translations (no template patching).",
    )
    group.add_argument(
        "--audit-langs",
        action="store_true",
        help="Report which language files still have English (untranslated) values.",
    )
    group.add_argument(
        "--fix-lang",
        metavar="LANG",
        help="Re-translate English values in a language file. Use 'all' for every language.",
    )
    args = parser.parse_args()

    if not GEMINI_API_KEY and (args.fix or args.fix_all or args.translate_only or args.fix_lang):
        sys.exit("GEMINI_API_KEY environment variable not set.")

    if args.report:
        cmd_report()

    elif args.fix:
        p = resolve_template(args.fix)
        if not p.exists():
            sys.exit(f"Template not found: {p}")
        cmd_fix(p)

    elif args.fix_all:
        paths = translatable_templates()
        print(f"Processing {len(paths)} templates…\n")
        for i, path in enumerate(paths, 1):
            rel = path.relative_to(TEMPLATES_DIR)
            print(f"[{i}/{len(paths)}] {rel}")
            try:
                cmd_fix(path)
            except Exception as e:  # noqa: BLE001 - one template's Gemini fix failing (API error, malformed response) must not abort the batch run over the rest
                print(f"  ERROR: {e}")
            time.sleep(2)  # rate limit between templates

    elif args.translate_only:
        cmd_translate_only()

    elif args.audit_langs:
        cmd_audit_langs()

    elif args.fix_lang:
        cmd_fix_lang(args.fix_lang)


if __name__ == "__main__":
    main()
