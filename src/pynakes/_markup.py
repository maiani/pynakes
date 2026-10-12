"""Convert provider markup (MathML, JATS, HTML) in title-like values to LaTeX.

Crossref and DOI content negotiation hand back titles exactly as publishers
deposit them, and publishers deposit structure: APS wraps a formula in
``<mml:math>`` MathML, JATS sources use ``<inline-formula>``, ``<italic>`` and
``<sub>``, and others send plain HTML ``<i>``. Stored verbatim in a ``.bib``
title the markup is noise that LaTeX typesets literally.

:func:`markup_to_latex` is the one conversion every route shares: import (via
:class:`~pynakes.providers.records.ReferenceMetadata`), ``normalize``, and
``verify --online``'s title comparison. A chemical formula becomes text with
math subscripts (``RuO$_2$``), a lone symbol becomes inline math (``$d$``,
``$\\kappa$``), italics become ``\\textit``, and any other element is dropped
while its text is kept. :func:`has_markup` is the detector ``lint`` uses.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

#: Fields that hold a title of some kind, where provider markup ends up.
TITLE_LIKE_FIELDS = (
    "title",
    "subtitle",
    "titleaddon",
    "shorttitle",
    "booktitle",
    "booksubtitle",
    "maintitle",
    "mainsubtitle",
    "eventtitle",
    "origtitle",
    "journal",
    "journaltitle",
    "series",
)

# Element names (namespace prefix stripped) recognized as markup. A bare ``<x>``
# in a title is too ambiguous to strip, so detection requires a known name or an
# explicit namespace prefix such as ``mml:`` or ``jats:``.
_KNOWN_TAGS = frozenset(
    {
        # MathML
        "math", "mrow", "mi", "mn", "mo", "mtext", "ms", "mspace", "msub", "msup",
        "msubsup", "mfrac", "msqrt", "mroot", "mover", "munder", "munderover",
        "mstyle", "mpadded", "mphantom", "mfenced", "menclose", "semantics",
        "annotation", "annotation-xml", "mmultiscripts", "mprescripts", "none",
        # JATS
        "inline-formula", "disp-formula", "alternatives", "tex-math", "italic", "bold",
        "sc", "roman", "monospace", "underline", "overline", "styled-content", "named-content",
        # HTML
        "i", "b", "em", "strong", "sub", "sup", "span", "u", "small", "br", "p", "scp", "font",
    }
)  # fmt: skip

_TAG_RE = re.compile(r"<(/?)(?:([A-Za-z][\w.-]*):)?([A-Za-z][\w.-]*)(?=[\s/>])[^<>]*?(/?)>")

_GREEK = {
    "α": r"\alpha", "β": r"\beta", "γ": r"\gamma", "δ": r"\delta", "ε": r"\epsilon",
    "ϵ": r"\epsilon", "ζ": r"\zeta", "η": r"\eta", "θ": r"\theta", "ϑ": r"\vartheta",
    "ι": r"\iota", "κ": r"\kappa", "λ": r"\lambda", "μ": r"\mu", "ν": r"\nu", "ξ": r"\xi",
    "π": r"\pi", "ρ": r"\rho", "σ": r"\sigma", "τ": r"\tau", "υ": r"\upsilon",
    "φ": r"\phi", "ϕ": r"\phi", "χ": r"\chi", "ψ": r"\psi", "ω": r"\omega",
    "Γ": r"\Gamma", "Δ": r"\Delta", "Θ": r"\Theta", "Λ": r"\Lambda", "Ξ": r"\Xi",
    "Π": r"\Pi", "Σ": r"\Sigma", "Φ": r"\Phi", "Ψ": r"\Psi", "Ω": r"\Omega",
}  # fmt: skip
_OPERATORS = {
    "−": "-", "–": "-", "×": r"\times", "±": r"\pm", "∓": r"\mp", "·": r"\cdot",
    "⋅": r"\cdot", "→": r"\to", "←": r"\leftarrow", "↔": r"\leftrightarrow",
    "∼": r"\sim", "≈": r"\approx", "≃": r"\simeq", "≤": r"\leq", "≥": r"\geq",
    "≠": r"\neq", "∞": r"\infty", "∂": r"\partial", "∇": r"\nabla", "⊥": r"\perp",
    "∥": r"\parallel", "′": "'", "″": "''", "⊗": r"\otimes", "⊕": r"\oplus", "ℏ": r"\hbar",
}  # fmt: skip
_ACCENTS = {"~": r"\tilde", "˜": r"\tilde", "^": r"\hat", "ˆ": r"\hat", "¯": r"\bar",
            "‾": r"\bar", "→": r"\vec", "˙": r"\dot", "¨": r"\ddot"}  # fmt: skip
_TEXT_WRAPPERS = {"i": r"\textit", "em": r"\textit", "italic": r"\textit",
                  "b": r"\textbf", "strong": r"\textbf", "bold": r"\textbf",
                  "sc": r"\textsc", "scp": r"\textsc"}  # fmt: skip
_CHARGE_RE = re.compile(r"^[0-9]*[+\-−]?$|^[+\-−][0-9]*$")


@dataclass
class _Node:
    name: str
    children: list[_Node | str] = field(default_factory=list)


def _is_markup_tag(match: re.Match[str]) -> bool:
    return bool(match.group(2)) or match.group(3).lower() in _KNOWN_TAGS


def has_markup(value: str) -> bool:
    """Return whether ``value`` contains MathML, JATS, or HTML element markup."""
    return any(_is_markup_tag(match) for match in _TAG_RE.finditer(value))


def _parse(value: str) -> _Node:
    """Build a tolerant element tree: stray closers are ignored, open tags close at the end."""
    root = _Node("#root")
    stack = [root]
    position = 0
    for match in _TAG_RE.finditer(value):
        if not _is_markup_tag(match):
            continue
        if match.start() > position:
            stack[-1].children.append(value[position : match.start()])
        position = match.end()
        closing, name, self_closing = match.group(1), match.group(3).lower(), match.group(4)
        if closing:
            for depth in range(len(stack) - 1, 0, -1):
                if stack[depth].name == name:
                    del stack[depth:]
                    break
            continue
        node = _Node(name)
        stack[-1].children.append(node)
        if not self_closing and name not in {"br", "mspace", "none", "mprescripts"}:
            stack.append(node)
    stack[-1].children.append(value[position:])
    return root


def _text(node: _Node | str) -> str:
    if isinstance(node, str):
        return html.unescape(node)
    return "".join(_text(child) for child in node.children)


def _elements(node: _Node) -> list[_Node]:
    """Element children, skipping the whitespace between them."""
    return [child for child in node.children if isinstance(child, _Node)]


def _script(value: str) -> str:
    value = value.strip()
    return value if len(value) == 1 else f"{{{value}}}"


def _math_symbol(text: str) -> str:
    out = []
    for char in text:
        symbol = _GREEK.get(char) or _OPERATORS.get(char)
        out.append(f"{symbol} " if symbol and symbol.startswith("\\") else (symbol or char))
    return "".join(out).strip()


def _math(node: _Node | str) -> str:
    """Render a MathML subtree as math-mode LaTeX."""
    if isinstance(node, str):
        return _math_symbol(" ".join(html.unescape(node).split()))
    name = node.name
    kids = _elements(node)
    if name in {"mi", "mn", "mo", "ms"}:
        text = _text(node).strip()
        if name == "mi" and len(text) > 1 and not any(ch in _GREEK for ch in text):
            return rf"\mathrm{{{text}}}"
        return _math_symbol(text)
    if name == "mtext":
        text = _text(node).strip()
        return rf"\mathrm{{{text}}}" if text else ""
    if name in {"annotation", "annotation-xml", "mphantom"}:
        return ""
    if name == "semantics":
        return _math(kids[0]) if kids else ""
    if name in {"msub", "msup", "msubsup"} and len(kids) >= 2:
        base = _math(kids[0])
        if name == "msub":
            return f"{base}_{_script(_math(kids[1]))}"
        if name == "msup":
            return f"{base}^{_script(_math(kids[1]))}"
        sup = _math(kids[2]) if len(kids) > 2 else ""
        return f"{base}_{_script(_math(kids[1]))}^{_script(sup)}"
    if name == "mfrac" and len(kids) == 2:
        return rf"\frac{{{_math(kids[0])}}}{{{_math(kids[1])}}}"
    if name == "msqrt":
        return rf"\sqrt{{{''.join(_math(kid) for kid in kids)}}}"
    if name in {"mover", "munder", "munderover"} and len(kids) >= 2:
        accent = _ACCENTS.get(_text(kids[-1]).strip())
        base = _math(kids[0])
        return f"{accent}{{{base}}}" if accent and name == "mover" else base
    return "".join(_math(child) for child in node.children).strip()


def _chemical(node: _Node) -> str | None:
    """Render a formula such as ``RuO2`` or ``Fe3+`` in text mode, or ``None``.

    A formula qualifies when it is a run of capitalized element symbols with
    numeric or charge sub/superscripts — what an author would type as
    ``RuO$_2$`` rather than as math. A single letter (``T1``, ``x2``) is a
    symbol with an index, so it stays math.
    """
    parts: list[str] = []
    saw_element = False

    def walk(item: _Node) -> bool:
        nonlocal saw_element
        if item.name in {"math", "mrow", "mstyle", "semantics", "inline-formula"}:
            kids = _elements(item)
            if item.name == "semantics":
                kids = kids[:1]
            return all(walk(kid) for kid in kids)
        if item.name in {"mi", "mtext"}:
            text = _text(item).strip()
            if not re.fullmatch(r"(?:[A-Z][a-z]?)+", text):
                return False
            saw_element = True
            parts.append(text)
            return True
        if item.name == "mn":
            text = _text(item).strip()
            parts.append(text)
            return bool(re.fullmatch(r"[0-9.]+", text))
        if item.name in {"msub", "msup"}:
            kids = _elements(item)
            if len(kids) != 2 or not walk(kids[0]):
                return False
            script = _text(kids[1]).strip()
            if not _CHARGE_RE.match(script) and not re.fullmatch(r"[0-9.]*[a-zδx]?", script):
                return False
            script = script.replace("−", "-")
            parts.append(
                f"$_{_script(script)}$" if item.name == "msub" else f"$^{_script(script)}$"
            )
            return True
        return False

    if not walk(node) or not saw_element:
        return None
    letters = sum(ch.isalpha() for part in parts if not part.startswith("$") for ch in part)
    return "".join(parts) if letters >= 2 else None


def _render(node: _Node | str) -> str:
    """Render text-mode content."""
    if isinstance(node, str):
        return html.unescape(node)
    name = node.name
    if name in {"math", "inline-formula", "disp-formula", "alternatives"}:
        kids = _elements(node)
        if name == "alternatives" or (name != "math" and kids):
            tex = next((kid for kid in kids if kid.name == "tex-math"), None)
            mathml = next((kid for kid in kids if kid.name == "math"), None)
            if mathml is not None:
                return _render(mathml)
            if tex is not None:
                return _tex_math(_text(tex))
            return "".join(_render(child) for child in node.children)
        chemical = _chemical(node)
        if chemical is not None:
            return chemical
        body = _math(node)
        return f"${body}$" if body else ""
    if name == "tex-math":
        return _tex_math(_text(node))
    if name in {"sub", "sup"}:
        body = " ".join(_text(node).split())
        return f"$_{_script(body)}$" if name == "sub" else f"$^{_script(body)}$"
    inner = "".join(_render(child) for child in node.children)
    wrapper = _TEXT_WRAPPERS.get(name)
    if wrapper and inner.strip():
        return f"{wrapper}{{{inner.strip()}}}"
    if name in {"br", "p"}:
        return f" {inner} "
    return inner


def _tex_math(value: str) -> str:
    value = value.strip()
    value = re.sub(r"\\begin\{document\}|\\end\{document\}|\\documentclass.*?\n", "", value)
    value = value.strip().strip("$").strip()
    return f"${value}$" if value else ""


_SPACE_BEFORE_PUNCT_RE = re.compile(r"(?<=[$}])\s+(?=[-,.;:)’'])")
_SPACE_AFTER_OPEN_RE = re.compile(r"(?<=[(‘])\s+(?=[$\\])")


def markup_to_latex(value: str) -> str:
    """Return ``value`` with MathML/JATS/HTML markup converted to LaTeX.

    A value without recognized markup is returned unchanged, whitespace
    included, so applying this to every title is safe.
    """
    if not has_markup(value):
        return value
    rendered = _render(_parse(value))
    rendered = " ".join(rendered.split())
    # Publishers pretty-print markup on its own lines, so a formula followed by
    # a hyphen (``RuO2-based``) arrives as ``</math>\n  -based``.
    rendered = _SPACE_BEFORE_PUNCT_RE.sub("", rendered)
    return _SPACE_AFTER_OPEN_RE.sub("", rendered)


def comparable_title(value: str) -> str:
    """Return ``value`` reduced for comparing titles across markup conventions.

    Provider markup is converted first, then LaTeX math, macro names, and
    grouping are flattened to their letters, so ``RuO$_2$``, ``RuO$_{2}$``,
    ``{RuO$_2$}`` and MathML ``RuO<sub>2</sub>`` all compare equal.
    """
    text = markup_to_latex(value)
    text = re.sub(r"\\(?:mathrm|textit|textbf|textsc|emph|text)\b", "", text)
    text = text.replace("\\", "")
    return re.sub(r"[$_^{}]", "", text)
