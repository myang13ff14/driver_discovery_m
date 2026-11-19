"""Clio-style overview figure: real calls traced from transcript to L1 category.

Columns: call transcript -> extracted request (step 1) -> L3 cluster (steps 2+4)
-> L1/L2 hierarchy (step 5). All text and counts come from the pipeline outputs.
"""

import json
import textwrap
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_rgb
from matplotlib.patches import FancyBboxPatch, Circle

STAGE = Path(__file__).resolve().parent.parent  # unsupervised/
OUT = Path(__file__).resolve().parent / "pipeline_overview.png"

# (genuuid, request_idx) of the traced examples, top to bottom
EXAMPLES = [
    ("[GEN_d5075e6ef4f5d96e]", 0),
    ("[GEN_dd031df2a8c8b7f3]", 1),
    ("[GEN_f7af7de416db0d1e]", 0),
    ("[GEN_758fab7e1304ec6b]", 0),
    ("[GEN_3bc75c90690a38f1]", 1),
]
L1_COLORS = {"Device Hardware": "#2a78d6", "Connectivity & Peripherals": "#1baf7a",
             "Purchases & Coverage": "#eda100"}

BG, CARD, EDGE = "#fbf4f0", "#fdfbf9", "#ebe3dd"
TEXT, MUTED, ACCENT, SEP = "#1f1f1e", "#6b6a64", "#c9502b", "#f0a58a"
PX = 72 / 150  # canvas px -> points at 150 dpi

# canvas is 2400 x 1520 px, y grows downward
COLS = {1: (70, 470), 2: (640, 470), 3: (1210, 490), 4: (1800, 540)}
ROW_TOP = [300, 545, 790, 1035, 1280]
ROW_H = 200


def tint(c, a):
    r, g, b = to_rgb(c)
    return (r + (1 - r) * a, g + (1 - g) * a, b + (1 - b) * a)


def rbox(ax, x, y, w, h, fc, ec=EDGE, lw=1.2, r=22):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                fc=fc, ec=ec, lw=lw))


def txt(ax, x, y, s, px, color=TEXT, weight="normal", **kw):
    return ax.text(x, y, s, fontsize=px * PX, color=color, weight=weight, va="top", **kw)


def width(ax, t):
    """Rendered width of a text artist in data (canvas px) units."""
    bb = t.get_window_extent(renderer=ax.figure.canvas.get_renderer())
    inv = ax.transData.inverted()
    return inv.transform((bb.x1, 0))[0] - inv.transform((bb.x0, 0))[0]


def wrap(s, chars, lines):
    out = textwrap.wrap(s, chars)
    if len(out) > lines:
        out = out[:lines]
        out[-1] = out[-1][: chars - 1].rstrip() + "…"
    return out


def chip(ax, x, y, label, px=15):
    w = len(label) * px * 0.72 + 24
    rbox(ax, x, y, w, 34, "#ffffff", ec="#d9d2cc", lw=1, r=17)
    ax.text(x + w / 2, y + 17, label.upper(), fontsize=px * PX, color=MUTED, weight="bold",
            ha="center", va="center")
    return w


def connector(ax, x1, y1, x2, y2, lock=True):
    """Dot -> elbow line -> arrow, with an accent badge marking the pipeline step."""
    xm = x1 + 32
    ax.add_patch(Circle((x1, y1), 7, color="#9a9590", zorder=3))
    ax.plot([x1, xm, xm, x2 - 10], [y1, y1, y2, y2], color="#9a9590", lw=2, zorder=2,
            solid_joinstyle="round")
    ax.annotate("", xy=(x2, y2), xytext=(x2 - 14, y2),
                arrowprops=dict(arrowstyle="-|>", color="#9a9590", lw=2, mutation_scale=18))
    if lock:
        ax.add_patch(Circle((xm, y1), 15, color=ACCENT, zorder=4))
        ax.text(xm, y1, "›", color="white", fontsize=22 * PX, ha="center", va="center",
                weight="bold", zorder=5)


def main():
    calls = {c["genuuid"]: c for c in json.loads(
        (STAGE / "step1_extraction/result/extractions.json").read_text())["calls"]}
    labels = {(r["genuuid"], r["request_idx"]): r for r in json.loads(
        (STAGE / "step5_hierarchy/result/labels.json").read_text())}
    H = json.loads((STAGE / "step5_hierarchy/result/hierarchy.json").read_text())
    l2_by_id = {p["id"]: p for p in H["L2"]}
    l3_size = {c["name"]: c["size"] for c in H["L3"]}
    l2_size = {p["name"]: p["size"] for p in H["L2"]}

    ex = []
    for g, i in EXAMPLES:
        req = calls[g]["requests"][i]
        ex.append({**req, **labels[(g, i)], "turns": calls[g]["turns"]})

    fig = plt.figure(figsize=(16, 1520 / 150), dpi=150)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, 2400)
    ax.set_ylim(1520, 0)
    ax.axis("off")
    fig.patch.set_facecolor(BG)

    # column separators
    for x in (590, 1160, 1750):
        ax.plot([x, x], [0, 1520], color=SEP, lw=5, ls=(0, (2, 2)))

    heads = [
        (1, "INPUT", "Call transcripts", "1,000 de-identified US support calls, speech-to-text"),
        (2, "STEP 1 · LLM, ONE CALL AT A TIME", "Extracted requests",
         "Normalized request per issue, with area, ask and outcome"),
        (3, "STEPS 2 + 4 · MPNET + UMAP + OPTICS, LLM NAMES", "Initial clusters",
         f"{len(H['L3'])} clusters of similar requests (L3)"),
        (4, "STEP 5 · LLM GROUPS BOTTOM-UP", "Call-driver hierarchy",
         f"L3 grouped into {len(H['L2'])} areas (L2) and {len(H['L1'])} domains (L1)"),
    ]
    for col, tag, title, sub in heads:
        x, w = COLS[col]
        txt(ax, x, 50, tag, 17, color=ACCENT if col > 1 else MUTED, weight="bold")
        txt(ax, x, 95, title, 44, weight="bold")
        for k, line in enumerate(textwrap.wrap(sub, 42)):
            txt(ax, x, 172 + k * 32, line, 22, color=MUTED)

    # column 1: transcript snippets; column 2: extracted requests
    for e, top in zip(ex, ROW_TOP):
        x, w = COLS[1]
        rbox(ax, x, top, w, ROW_H, CARD)
        y = top + 26
        for who, quote in (("Customer:", e["customer_quote"]), ("Agent:", e["agent_quote"])):
            lines = wrap(f"{who} “{quote}”", 36, 2)
            for k, line in enumerate(lines):
                if k == 0:
                    label = txt(ax, x + 26, y, who, 21, weight="bold")
                    txt(ax, x + 26 + width(ax, label) + 7, y, line[len(who):].lstrip(), 21)
                else:
                    txt(ax, x + 26, y, line, 21)
                y += 32
            y += 14

        x, w = COLS[2]
        rbox(ax, x, top, w, ROW_H, CARD)
        txt(ax, x + 26, top + 22, "REQUEST", 15, color=MUTED, weight="bold")
        for k, line in enumerate(wrap(e["request"], 36, 2)):
            txt(ax, x + 26, top + 52 + k * 32, line, 23)
        cx = x + 26
        for label in (e["category"], e["request_type"].replace("_", " "), e["outcome"].replace("_", " ")):
            cx += chip(ax, cx, top + ROW_H - 56, label) + 10
        connector(ax, COLS[1][0] + COLS[1][1], top + ROW_H / 2, x, top + ROW_H / 2)

    # column 3: one card per L3 cluster, members are the traced requests
    groups = {}
    for idx, e in enumerate(ex):
        groups.setdefault(e["L3"], []).append(idx)
    member_y = {}
    l3_card_mid = {}
    x, w = COLS[3]
    for l3, idxs in groups.items():
        color = L1_COLORS[ex[idxs[0]]["L1"]]
        top = ROW_TOP[idxs[0]] + (0 if len(idxs) > 1 else -10)
        title = wrap(l3, 34, 2)
        h = 30 + len(title) * 34 + 16 + len(idxs) * 62 + 44
        rbox(ax, x, top, w, h, tint(color, 0.88), ec=tint(color, 0.6), lw=1.5)
        for k, line in enumerate(title):
            txt(ax, x + 26, top + 22 + k * 34, line, 25)
        y = top + 30 + len(title) * 34 + 14
        for i in idxs:
            rbox(ax, x + 18, y, w - 36, 50, "#ffffff", ec=tint(color, 0.7), lw=1, r=25)
            txt(ax, x + 38, y + 13, wrap(ex[i]["request"], 37, 1)[0], 19)
            member_y[i] = y + 25
            y += 62
        more = l3_size[l3] - len(idxs)
        txt(ax, x + 38, y + 4, f"+ {more} more requests  ·  {l3_size[l3]} in cluster", 18, color=MUTED)
        l3_card_mid[l3] = (top + h / 2, color)
    for i, e in enumerate(ex):
        connector(ax, COLS[2][0] + COLS[2][1], ROW_TOP[i] + ROW_H / 2, x, member_y[i])

    # column 4: L1 boxes listing their largest L2s, highlighting the one each L3 rolls into
    x, w = COLS[4]
    shown_l1 = []
    for e in ex:
        if e["L1"] not in shown_l1:
            shown_l1.append(e["L1"])
    target_l2 = {e["L1"]: e["L2"] for e in ex}
    tops = {shown_l1[0]: 300, shown_l1[1]: 700, shown_l1[2]: 1010}
    l2_row_y = {}
    for g in H["L1"]:
        if g["name"] not in shown_l1:
            continue
        color = L1_COLORS[g["name"]]
        top = tops[g["name"]]
        kids = [l2_by_id[c]["name"] for c in g["children"]]
        rows = kids[:3] if target_l2[g["name"]] in kids[:3] else kids[:2] + [target_l2[g["name"]]]
        h = 80 + len(rows) * 62 + 12
        rbox(ax, x, top, w, h, tint(color, 0.72), ec=tint(color, 0.5), lw=1.5)
        txt(ax, x + 26, top + 22, g["name"], 27)
        ax.text(x + w - 26, top + 22, f"{g['size']} ({g['size'] / H['n_requests']:.0%})",
                fontsize=19 * PX, color=TEXT, ha="right", va="top")
        y = top + 74
        for name in rows:
            hit = name == target_l2[g["name"]]
            rbox(ax, x + 18, y, w - 36, 50, "#ffffff" if hit else tint(color, 0.88),
                 ec=tint(color, 0.3) if hit else tint(color, 0.75), lw=2 if hit else 1, r=25)
            txt(ax, x + 38, y + 12, name, 21, weight="bold" if hit else "normal")
            ax.text(x + w - 38, y + 25, str(l2_size[name]), fontsize=19 * PX, color=MUTED,
                    ha="right", va="center")
            if hit:
                l2_row_y[g["name"]] = y + 25
            y += 62
    for l3, idxs in groups.items():
        mid, _ = l3_card_mid[l3]
        connector(ax, COLS[3][0] + COLS[3][1], mid, x, l2_row_y[ex[idxs[0]]["L1"]])

    others = [g for g in H["L1"] if g["name"] not in shown_l1]
    rbox(ax, x, 1330, w, 58, "#efebe7", ec="#e3ddd8")
    txt(ax, x + 26, 1344, f"+ {len(others)} more domains", 25)
    for k, g in enumerate(others):
        rbox(ax, x, 1400 + k * 38, w, 32, "#f6f2ef", ec="#ece6e1", r=16)
        txt(ax, x + 26, 1405 + k * 38, f"{g['name']}  ·  {g['size']}", 17, color=MUTED)

    fig.savefig(OUT, facecolor=BG)
    print(f"saved {OUT}")


if __name__ == "__main__":
    main()
