#!/usr/bin/env python3
"""Generate the pynakes logo (``docs/assets/logo.svg``) with ``svg.py``.

Developer-only: not part of the package, and not run by the test suite. It needs
the third-party ``svg.py`` package (``pip install svg.py``).

The logo is a parchment catalogue sheet on a dark navy rounded tile: its
top-right corner is rolled up into a scroll, and it carries a green at sign
over three catalogue lines of falling length. Every shape is in the 256x256
view box. The catalogue lines are 8 units thick on rows
24 units apart, centred on ``8k + 4``, so they land on whole pixels in the 32px
favicon.

Usage:
    python scripts/make_logo.py                         # print the SVG
    python scripts/make_logo.py -o docs/assets/logo.svg
"""

import argparse
import math
import re
import sys
from pathlib import Path

import svg
from svg import Arc, C, H, L, M, V, Z

SIZE = 256

NAVY = ("#17324b", "#10253a", "#0b1b2b")
PAPER = ("#fffaf0", "#fbf5e8", "#f0dfbd")
ROLL = ("#fff7e5", "#e5c693", "#c49653")
ROLL_INNER = "#8e6335"
AT_GREEN = "#1d7a5e"
INK = "#10273c"

# The sheet's edges and its rounded-corner radius. The top-right corner is
# rolled up instead.
LEFT, TOP, RIGHT, BOTTOM = 40, 32, 196, 224
CORNER = 22
# The roll: its radius, and how far its centre sits inside the right edge. Its
# top is flush with the sheet's top edge.
ROLL_RADIUS = 20
ROLL_INSET = 2
ROLL_CX, ROLL_CY = RIGHT - ROLL_INSET, TOP + ROLL_RADIUS
# Where the right edge starts to bend in towards the roll, and where it meets
# the roll's underside (as an angle on the roll, clockwise from three o'clock).
ROLL_JOIN_Y = ROLL_CY + ROLL_RADIUS + 12
ROLL_JOIN_ANGLE = math.radians(110)

# Text block: left edge of the catalogue lines, their rows, and where each ends.
TEXT_X = 72
LINE_WIDTH = 8
LINES = ((140, 164), (164, 144), (188, 118))

# The at sign: its height, and the height of its centre.
AT_HEIGHT = 50
AT_CY = 90

# The at sign of TeX Gyre Heros Bold, in font units (y up). TeX Gyre fonts are
# released under the GUST Font License.
AT_SIGN = (
    "M959 366C959 571 766 741 532 741C265 741 41 519 41 258C41 35 243 -144 497 -144"
    "C570 -144 650 -130 735 -98L699 -8C607 -32 553 -40 502 -40C305 -40 152 95 152 273"
    "C152 469 322 638 519 638C696 638 846 509 846 354C846 250 774 146 698 146"
    "C680 146 664 158 664 174C664 182 667 197 674 218L748 509H637L624 467"
    "C596 508 557 529 508 529C371 529 264 394 264 246C264 136 339 54 437 54"
    "C485 54 526 71 568 110C584 70 623 49 681 49C843 49 959 216 959 366Z"
    "M579 360C574 252 530 145 452 145C407 145 371 189 371 245C371 345 428 438 503 438"
    "C546 438 579 407 579 365Z"
)
AT_SIGN_BOUNDS = (41, -144, 959, 741)


def outline(d: str) -> list[svg.PathData]:
    """Parse an absolute M/L/H/V/C/Z path string into ``svg.py`` commands."""
    commands = {"M": M, "L": L, "H": H, "V": V, "C": C, "Z": Z}
    return [
        commands[op](*(float(n) for n in re.findall(r"-?\d+(?:\.\d+)?", args)))
        for op, args in re.findall(r"([MLHVCZ])([^MLHVCZ]*)", d)
    ]


def _roll_bend() -> list[svg.PathData]:
    """The sheet's edge from inside the roll, out of its underside, and down.

    The paper leaves the roll along its tangent, heading right, and bends down
    into the sheet's right edge: the edge curves left as it rises into the roll.
    """
    r, cx, cy, a = ROLL_RADIUS, ROLL_CX, ROLL_CY, ROLL_JOIN_ANGLE
    join = (cx + r * math.cos(a), cy + r * math.sin(a))
    leaving = (math.sin(a), -math.cos(a))
    reach = 6
    return [
        L(cx, cy),
        L(*join),
        C(
            join[0] + reach * leaving[0],
            join[1] + reach * leaving[1],
            RIGHT,
            ROLL_JOIN_Y - reach,
            RIGHT,
            ROLL_JOIN_Y,
        ),
    ]


SHEET = [
    M(LEFT + CORNER, TOP),
    H(ROLL_CX),
    *_roll_bend(),
    V(BOTTOM - CORNER),
    Arc(CORNER, CORNER, 0, False, True, RIGHT - CORNER, BOTTOM),
    H(LEFT + CORNER),
    Arc(CORNER, CORNER, 0, False, True, LEFT, BOTTOM - CORNER),
    V(TOP + CORNER),
    Arc(CORNER, CORNER, 0, False, True, LEFT + CORNER, TOP),
    Z(),
]


def gradient(
    id_: str,
    stops: tuple[str, str, str],
    mid: float,
    start: tuple[float, float],
    end: tuple[float, float],
) -> svg.LinearGradient:
    """A three-stop user-space linear gradient from ``start`` to ``end``."""
    return svg.LinearGradient(
        id=id_,
        x1=start[0],
        y1=start[1],
        x2=end[0],
        y2=end[1],
        gradientUnits="userSpaceOnUse",
        elements=[
            svg.Stop(offset=offset, stop_color=color)
            for offset, color in zip((0, mid, 1), stops, strict=True)
        ],
    )


def drop_shadow() -> svg.Filter:
    """A soft shadow cast 5 units below the sheet."""
    return svg.Filter(
        id="shadow",
        x=-0.1,
        y=-0.1,
        width=1.2,
        height=1.2,
        extra={"color-interpolation-filters": "sRGB"},
        elements=[
            svg.FeGaussianBlur(in_="SourceAlpha", stdDeviation=5, result="blur"),
            svg.FeOffset(in_="blur", dx=0, dy=5, result="offsetBlur"),
            svg.FeFlood(flood_color="#020914", flood_opacity=0.25, result="shadowColor"),
            svg.FeComposite(in_="shadowColor", in2="offsetBlur", operator="in", result="shadow"),
            svg.FeMerge(
                elements=[svg.FeMergeNode(in_="shadow"), svg.FeMergeNode(in_="SourceGraphic")]
            ),
        ],
    )


def definitions() -> svg.Defs:
    r = ROLL_RADIUS
    return svg.Defs(
        elements=[
            gradient("navy", NAVY, 0.5, (28, 20), (226, 240)),
            gradient("paper", PAPER, 0.62, (LEFT + 16, TOP + 4), (RIGHT - 14, BOTTOM - 2)),
            gradient(
                "roll", ROLL, 0.5, (ROLL_CX - r * 0.7, ROLL_CY - r), (ROLL_CX + r, ROLL_CY + r)
            ),
            drop_shadow(),
            svg.Filter(
                id="soften",
                x=-0.2,
                y=-0.2,
                width=1.4,
                height=1.4,
                elements=[svg.FeGaussianBlur(stdDeviation=2.5)],
            ),
            svg.ClipPath(id="paperClip", elements=[svg.Path(d=SHEET)]),
        ]
    )


def roll() -> list[svg.Element]:
    """The rolled-up top-right corner; the sheet outline bends into its underside."""
    r, cx, cy = ROLL_RADIUS, ROLL_CX, ROLL_CY
    # The roll rests on the sheet, so it casts a soft shadow onto it.
    contact = svg.Circle(
        cx=cx - 2,
        cy=cy + 3,
        r=r,
        fill=ROLL_INNER,
        opacity=0.3,
        filter="url(#soften)",
        clip_path="url(#paperClip)",
    )
    body = svg.Circle(cx=cx, cy=cy, r=r, fill="url(#roll)")
    # The sheet's top edge wrapping into the roll: half-turns of shrinking
    # radius, starting where the top edge meets the roll.
    turns = ((-19, 12), (12, -8), (-8, 3))
    spiral = svg.Path(
        d=[
            M(cx, cy + turns[0][0]),
            *(
                Arc(abs(end - start) / 2, abs(end - start) / 2, 0, False, False, cx, cy + end)
                for start, end in turns
            ),
        ],
        fill="none",
        stroke=ROLL_INNER,
        stroke_width=1.6,
        stroke_linecap="round",
        opacity=0.85,
    )
    return [contact, body, spiral]


def sheet() -> svg.G:
    """The parchment with its roll and highlights, under one shadow."""
    top_highlight = svg.Path(
        d=[M(LEFT + 20, TOP + 8), H(RIGHT - 40)],
        fill="none",
        stroke="#ffffff",
        stroke_width=2.4,
        stroke_linecap="round",
        opacity=0.34,
        clip_path="url(#paperClip)",
    )
    side_highlight = svg.Path(
        d=[M(LEFT + 8, TOP + 37), V(BOTTOM - 32)],
        fill="none",
        stroke="#ffffff",
        stroke_width=1.8,
        stroke_linecap="round",
        opacity=0.22,
        clip_path="url(#paperClip)",
    )
    return svg.G(
        filter="url(#shadow)",
        elements=[
            svg.Path(d=SHEET, fill="url(#paper)"),
            top_highlight,
            side_highlight,
            *roll(),
        ],
    )


def at_sign() -> svg.Path:
    """The at sign, scaled to ``AT_HEIGHT`` with its left edge on the lines' caps."""
    x0, y0, _, y1 = AT_SIGN_BOUNDS
    scale = AT_HEIGHT / (y1 - y0)
    left = TEXT_X - LINE_WIDTH / 2
    return svg.Path(
        d=outline(AT_SIGN),
        fill=AT_GREEN,
        transform=[
            svg.Translate(left - x0 * scale, AT_CY + (y0 + y1) / 2 * scale),
            svg.Scale(scale, -scale),
        ],
    )


def catalogue_lines() -> svg.G:
    return svg.G(
        fill="none",
        stroke=INK,
        stroke_width=LINE_WIDTH,
        elements=[svg.Path(d=[M(TEXT_X, y), H(end)], stroke_linecap="round") for y, end in LINES],
    )


def logo() -> svg.SVG:
    return svg.SVG(
        viewBox=svg.ViewBoxSpec(0, 0, SIZE, SIZE),
        elements=[
            svg.Title(text="Pynakes app icon"),
            svg.Desc(
                text="A parchment catalogue with an at sign and three list lines "
                "on a dark navy rounded square."
            ),
            definitions(),
            svg.Rect(x=8, y=8, width=240, height=240, rx=48, fill="url(#navy)"),
            sheet(),
            at_sign(),
            catalogue_lines(),
        ],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the pynakes logo SVG.")
    parser.add_argument("-o", "--output", type=Path, help="write here instead of stdout")
    args = parser.parse_args(argv)
    text = f"{logo()}\n"
    if args.output is None:
        sys.stdout.write(text)
    else:
        args.output.write_text(text, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
