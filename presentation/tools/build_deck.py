"""Build ProofCam_Meta_Global_AI_Hackathon.pptx (16:9, native editable shapes/text, speaker notes, transitions).

Every screenshot/photo is authentic (see ../ASSET_MANIFEST.md). Video zones are labelled placeholders: no footage is
invented. Usage: python build_deck.py <presentation_dir>
"""
import sys
from pathlib import Path

from lxml import etree
from PIL import Image
from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.dml import MSO_LINE_DASH_STYLE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

sys.path.insert(0, str(Path(__file__).parent))
from content import SLIDES  # noqa: E402

PRES = Path(sys.argv[1])
A = PRES / "assets"
W, H = 13.333, 7.5

# ------------------------------------------------------------------------------------------------ design tokens
BG, PANEL, PANEL2, LINE = "0A0C10", "12161D", "171C25", "262D3A"
TEXT, MUTED, SUBTLE = "EEF2F7", "A3ACBA", "6B7585"
BLUE, BLUE2, CYAN = "4C8DFF", "8DB6FF", "38BDF8"
GREEN, AMBER, RED = "2FD07A", "F7B23B", "FF5A4E"
SEMI, LIGHT, BODY, MONO = "Segoe UI Semibold", "Segoe UI Light", "Segoe UI", "Cascadia Mono"
PHONE_ASPECT = 0.4615  # iPhone screen recordings (e.g. 1179×2556)


def rgb(h):
    return RGBColor.from_string(h)


def In(v):
    return Inches(v)


# ------------------------------------------------------------------------------------------------ text helpers
class R:
    def __init__(self, text, size=18, color=TEXT, font=BODY, bold=False, italic=False, spc=None):
        self.text, self.size, self.color, self.font = text, size, color, font
        self.bold, self.italic, self.spc = bold, italic, spc


class Para:
    def __init__(self, runs, align="l", after=0, before=0, ls=None):
        self.runs, self.align, self.after, self.before, self.ls = runs, align, after, before, ls


def P(text, align="l", after=0, before=0, ls=None, **fmt):
    return Para([R(text, **fmt)], align, after, before, ls)


ALIGN = {"l": PP_ALIGN.LEFT, "c": PP_ALIGN.CENTER, "r": PP_ALIGN.RIGHT}
ANCHOR = {"t": MSO_ANCHOR.TOP, "m": MSO_ANCHOR.MIDDLE, "b": MSO_ANCHOR.BOTTOM}


def T(slide, x, y, w, h, paras, anchor="t", name=None, margin=0.0):
    tb = slide.shapes.add_textbox(In(x), In(y), In(w), In(h))
    tf = tb.text_frame
    tf.word_wrap = True
    tf.auto_size = MSO_AUTO_SIZE.NONE
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = In(margin)
    tf.vertical_anchor = ANCHOR[anchor]
    if isinstance(paras, Para):
        paras = [paras]
    for i, para in enumerate(paras):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = ALIGN[para.align]
        p.space_after, p.space_before = Pt(para.after), Pt(para.before)
        if para.ls:
            p.line_spacing = para.ls
        for r in para.runs:
            run = p.add_run()
            run.text = r.text
            f = run.font
            f.size, f.name, f.bold, f.italic = Pt(r.size), r.font, r.bold, r.italic
            f.color.rgb = rgb(r.color)
            if r.spc is not None:
                run._r.get_or_add_rPr().set("spc", str(int(r.spc * 100)))
    if name:
        tb.name = name
    return tb


# ------------------------------------------------------------------------------------------------ shape helpers
def box(slide, x, y, w, h, fill=None, line=None, lw=1.0, radius=0.0, dash=None, name=None, alpha=None,
        shape=None):
    kind = shape or (MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE)
    s = slide.shapes.add_shape(kind, In(x), In(y), In(w), In(h))
    if radius and kind == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = min(0.5, radius / min(w, h))
    if fill:
        s.fill.solid()
        s.fill.fore_color.rgb = rgb(fill)
        if alpha is not None:
            set_fill_alpha(s, alpha)
    else:
        s.fill.background()
    if line:
        s.line.color.rgb = rgb(line)
        s.line.width = Pt(lw)
        if dash:
            s.line.dash_style = dash
    else:
        s.line.fill.background()
    s.shadow.inherit = False
    if name:
        s.name = name
    tf = s.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    return s


def set_fill_alpha(shape, pct):
    clr = shape._element.spPr.find(qn("a:solidFill"))[0]
    a = etree.SubElement(clr, qn("a:alpha"))
    a.set("val", str(int(pct * 1000)))


def gradient(shape, stops, angle):
    """stops: [(pos 0-100, hex, opacity 0-100)], angle in degrees (0 = left→right)."""
    spPr = shape._element.spPr
    for tag in ("a:solidFill", "a:noFill", "a:gradFill"):
        for e in spPr.findall(qn(tag)):
            spPr.remove(e)
    g = etree.Element(qn("a:gradFill"))
    g.set("rotWithShape", "1")
    gs = etree.SubElement(g, qn("a:gsLst"))
    for pos, hexc, op in stops:
        s = etree.SubElement(gs, qn("a:gs"))
        s.set("pos", str(int(pos * 1000)))
        c = etree.SubElement(s, qn("a:srgbClr"))
        c.set("val", hexc)
        al = etree.SubElement(c, qn("a:alpha"))
        al.set("val", str(int(op * 1000)))
    lin = etree.SubElement(g, qn("a:lin"))
    lin.set("ang", str(int(angle * 60000)))
    lin.set("scaled", "0")
    spPr.find(qn("a:prstGeom")).addnext(g)


def line(slide, x1, y1, x2, y2, color=MUTED, w=1.25, head=None, dash=None, name=None):
    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, In(x1), In(y1), In(x2), In(y2))
    c.line.color.rgb = rgb(color)
    c.line.width = Pt(w)
    if dash:
        c.line.dash_style = dash
    if head:
        ln = c.line._get_or_add_ln()
        te = etree.SubElement(ln, qn("a:tailEnd"))
        te.set("type", head)
        te.set("w", "med")
        te.set("len", "med")
    if name:
        c.name = name
    return c


def pic(slide, path, x, y, w=None, h=None, cover=False, round_adj=None, border=None, bw=1.0, rot=0, alt=None,
        name=None):
    iw, ih = Image.open(path).size
    if w is None and h is None:
        raise ValueError("give w or h")
    if w is None:
        w = h * iw / ih
    if h is None:
        h = w * ih / iw
    p = slide.shapes.add_picture(str(path), In(x), In(y), In(w), In(h))
    if cover:
        target, src = w / h, iw / ih
        if src > target:
            ex = (1 - target / src) / 2
            p.crop_left = p.crop_right = ex
        else:
            ex = (1 - src / target) / 2
            p.crop_top = p.crop_bottom = ex
    if round_adj:
        prst = p._element.spPr.find(qn("a:prstGeom"))
        prst.set("prst", "roundRect")
        av = prst.find(qn("a:avLst"))
        if av is None:
            av = etree.SubElement(prst, qn("a:avLst"))
        gd = etree.SubElement(av, qn("a:gd"))
        gd.set("name", "adj")
        gd.set("fmla", f"val {int(round_adj)}")
    if border:
        p.line.color.rgb = rgb(border)
        p.line.width = Pt(bw)
    if rot:
        p.rotation = rot
    if alt:
        p._element.nvPicPr.cNvPr.set("descr", alt)
    if name:
        p.name = name
    return p


def icon(slide, name, x, y, size):
    return pic(slide, A / "icons" / f"{name}.png", x, y, w=size, h=size, alt=name.split("_")[0] + " icon")


def pill(slide, x, y, w, h, text, fg=TEXT, fill=PANEL2, line_c=None, size=11, font=SEMI, alpha=None, spc=None,
         align="c"):
    b = box(slide, x, y, w, h, fill=fill, line=line_c, lw=0.75, radius=h / 2, alpha=alpha)
    T(slide, x + 0.12, y, w - 0.24, h, P(text, size=size, color=fg, font=font, align=align, spc=spc), anchor="m")
    return b


TRANSITION_S = {"fast": 0.5, "med": 0.75, "slow": 1.0}  # PowerPoint's fixed durations for spd=


def transition(slide, slot_s, thru_black=False, spd="fast"):
    """Fade into this slide, then advance automatically. PowerPoint's video export plays the transition IN ADDITION to
    advTm, so advTm = slot - transition keeps every slide inside its planned slot (total video = sum of slots)."""
    ns = "http://schemas.openxmlformats.org/presentationml/2006/main"
    t = etree.Element(f"{{{ns}}}transition")
    t.set("spd", spd)
    t.set("advTm", str(int(round((slot_s - TRANSITION_S[spd]) * 1000))))
    f = etree.SubElement(t, f"{{{ns}}}fade")
    if thru_black:
        f.set("thruBlk", "1")
    slide._element.find(qn("p:clrMapOvr")).addnext(t)


def eyebrow(slide, text, x=0.75, y=0.55, w=11.8, color=BLUE):
    T(slide, x, y, w, 0.3, P(text, size=11, color=color, font=SEMI, spc=2.2))


def title(slide, text, x=0.75, y=0.86, w=11.8, size=38, color=TEXT, h=0.85):
    T(slide, x, y, w, h, P(text, size=size, color=color, font=SEMI, ls=0.95))


def footer(slide, n):
    box(slide, 0.75, 7.08, 0.12, 0.12, fill=BLUE, radius=0.03)
    T(slide, 0.95, 7.0, 3, 0.28, P("ProofCam", size=10, color=SUBTLE, font=SEMI, spc=0.6))
    T(slide, W - 1.75, 7.0, 1.0, 0.28, P(f"{n:02d}", size=10, color=SUBTLE, font=SEMI, align="r"))


def notes(slide, text):
    slide.notes_slide.notes_text_frame.text = text


def bg(slide):
    f = slide.background.fill
    f.solid()
    f.fore_color.rgb = rgb(BG)


def phone(slide, x, y, h, screen=None, name=None):
    """Phone bezel; `screen` is an image path (real app screenshot) or None (returns screen rect for placeholders)."""
    w = h * PHONE_ASPECT
    box(slide, x, y, w, h, fill="05070A", line="2E3644", lw=1.25, radius=0.42, name=(name + " · bezel") if name else None)
    inset = 0.075
    sx, sy, sw, sh = x + inset, y + inset, w - 2 * inset, h - 2 * inset
    if screen:
        pic(slide, screen, sx, sy, sw, sh, cover=True, round_adj=9000, alt="ProofCam app screenshot", name=name)
    return sx, sy, sw, sh


def video_placeholder(slide, x, y, h, letter, heading, sub):
    sx, sy, sw, sh = phone(slide, x, y, h, name=f"PHONE FRAME · RECORDING {letter}")
    b = box(slide, sx, sy, sw, sh, fill="0E131B", line=BLUE, lw=1.5, radius=0.34, dash=MSO_LINE_DASH_STYLE.DASH,
            name=f"VIDEO PLACEHOLDER · RECORDING {letter}")
    T(slide, sx + 0.15, sy + sh * 0.28, sw - 0.3, 2.9, [
        P("▶", size=34, color=BLUE, align="c", after=6),
        P("INSERT", size=16, color=BLUE, font=SEMI, align="c", spc=1.2),
        P(f"RECORDING {letter}", size=16, color=BLUE, font=SEMI, align="c", spc=1.2, after=4),
        P(heading, size=12.5, color=TEXT, font=SEMI, align="c", after=10),
        P("iPhone screen recording · portrait", size=10.5, color=MUTED, align="c", after=2),
        P(sub, size=10.5, color=MUTED, align="c", after=2),
        P("Replace this frame: see speaker notes", size=10.5, color=SUBTLE, align="c"),
    ], name=f"VIDEO PLACEHOLDER LABEL · RECORDING {letter}")
    return b, (sx, sy, sw, sh)


# ================================================================================================ build
prs = Presentation()
prs.slide_width, prs.slide_height = In(W), In(H)
blank = prs.slide_layouts[6]
cp = prs.core_properties
cp.title = "ProofCam — Meta Global AI Developer Hackathon (Push the Frontier)"
cp.author = "Daksh Vats"
cp.subject = "AI-guided verification of physical installations — Muse Spark 1.3 + SAM 3.1 + deterministic policy"
cp.keywords = "ProofCam; Meta Muse Spark 1.3; SAM 3.1; verification; hackathon"

TIMING = {n: d for n, _, _, d, *_ in SLIDES}
NARR = {n: (t, narr, cap, prod) for n, t, _, _, narr, cap, prod in SLIDES}
START = {n: s for n, _, s, *_ in SLIDES}


def new_slide(n=None):
    s = prs.slides.add_slide(blank)
    bg(s)
    return s


def std_notes(s, n, extra=""):
    t, narr, cap, prod = NARR[n]
    m, sec = divmod(START[n], 60)
    m2, sec2 = divmod(START[n] + TIMING[n], 60)
    notes(s, f"[{m}:{sec:02d}–{m2}:{sec2:02d} · {TIMING[n]} s] {t}\n\nNARRATION:\n{narr}\n\nON-SCREEN CAPTION (muted "
             f"viewing):\n{cap}\n\nPRODUCTION:\n{prod}" + (f"\n\n{extra}" if extra else ""))


ph = A / "photos"
ui = A / "ui"

# ------------------------------------------------------------------------------------------------ 1 · hook
s = new_slide()
px, pw = W - 5.625, 5.625
pic(s, ph / "B4_photo.jpg", px, 0, pw, H, alt="Rear of the author's PlayStation 5 with Ethernet and HDMI plugs")
dim = box(s, px, 0, pw, H, fill=BG, alpha=28)
fade = box(s, px - 0.02, 0, 3.2, H, fill=BG)
gradient(fade, [(0, BG, 100), (100, BG, 0)], 0)


def gx(v):
    return px + v / 1000 * pw


def gy(v):
    return v / 1000 * H


# Muse boxes (0-1000 grid) recorded for photo 4 of the real inspection
for (x1, y1, x2, y2), col, l1, l2 in [
    ((312, 355, 530, 452), GREEN, "LAN · plug seen by Muse", "SAM mask reaches the port ✓"),
    ((372, 545, 537, 680), AMBER, "HDMI OUT · plug seen by Muse", "no SAM corroboration ?"),
]:
    box(s, gx(x1), gy(y1), gx(x2) - gx(x1), gy(y2) - gy(y1), line=col, lw=1.75, dash=MSO_LINE_DASH_STYLE.DASH)
    cy = (gy(y1) + gy(y2)) / 2
    line(s, gx(x2), cy, 10.85, cy, color=col, w=1.0)
    box(s, 10.85, cy - 0.36, 2.4, 0.72, fill="0A0C10", alpha=86, line=col, lw=0.75, radius=0.1)
    T(s, 10.97, cy - 0.33, 2.2, 0.68, [P(l1, size=10, color=TEXT, font=SEMI), P(l2, size=10, color=col)], anchor="m")
for cx, cy, dx, dy in [(px + 0.35, 0.35, 1, 1), (W - 0.35, 0.35, -1, 1), (px + 0.35, H - 0.35, 1, -1), (W - 0.35, H - 0.35, -1, -1)]:
    line(s, cx, cy, cx + 0.42 * dx, cy, color=TEXT, w=1.5)
    line(s, cx, cy, cx, cy + 0.42 * dy, color=TEXT, w=1.5)
T(s, 0.75, 1.95, 6.6, 0.3, P("META GLOBAL AI DEVELOPER HACKATHON  ·  PUSH THE FRONTIER", size=10.5, color=BLUE, font=SEMI, spc=2))
T(s, 0.75, 2.4, 6.7, 2.5, [P("AI can recognise", size=46, font=SEMI, ls=0.92), P("what it sees.", size=46, font=SEMI, ls=0.92, after=14),
                           P("But can it prove", size=46, font=SEMI, color=BLUE, ls=0.92), P("what's true?", size=46, font=SEMI, color=BLUE, ls=0.92)])
T(s, 0.75, 5.45, 6.0, 0.5, P("Introducing ProofCam.", size=22, font=LIGHT, color=MUTED))
T(s, 0.75, 6.85, 6.6, 0.35, P("Photo: the author's PlayStation 5. Labels are what a live ProofCam inspection recorded "
                              "(Muse Spark 1.3 + SAM 3.1).", size=9.5, color=SUBTLE))
std_notes(s, 1, "ASSET: real photo 4 of inspection insp_92cc… (physical equipment). The two boxes are Muse's recorded "
                "port boxes for that photo; the labels state what the policy recorded (LAN: SAM-corroborated; HDMI OUT: "
                "Muse only).")
transition(s, TIMING[1], thru_black=True, spd="slow")

# ------------------------------------------------------------------------------------------------ 2 · problem
s = new_slide()
eyebrow(s, "THE PROBLEM")
title(s, "The physical world runs on assumptions.")
# column 1: photos
pic(s, ph / "B1_photo.jpg", 0.95, 2.25, w=2.1, h=1.575, border="F4F6F8", bw=3, rot=-7, alt="Overview photo")
pic(s, ph / "B2_photo.jpg", 2.35, 2.0, w=1.2, h=1.6, cover=True, border="F4F6F8", bw=3, rot=5, alt="Set-top box rear")
pic(s, ph / "B4_photo.jpg", 3.25, 2.3, w=1.12, h=1.5, cover=True, border="F4F6F8", bw=3, rot=-3, alt="PS5 rear")
T(s, 0.75, 4.25, 3.75, 1.2, [P("Photos are collected.", size=20, font=SEMI, after=4),
                             P("Pictures pile up after the work is done, with no link to what they prove.", size=13, color=MUTED, ls=1.1)])
# column 2: checklist
box(s, 4.99, 2.05, 3.35, 1.95, fill=PANEL, line=LINE, radius=0.16)
T(s, 5.22, 2.2, 3.0, 0.3, P("INSTALLATION CHECKLIST", size=10, color=SUBTLE, font=SEMI, spc=1.6))
for i, t in enumerate(["Router / set-top box installed", "Console cabled", "TV connected", "Signed off"]):
    icon(s, "circle-check_green", 5.22, 2.6 + i * 0.33, 0.24)
    T(s, 5.56, 2.57 + i * 0.33, 2.7, 0.3, P(t, size=13, color=TEXT))
T(s, 4.79, 4.25, 3.75, 1.2, [P("Checklists are completed.", size=20, font=SEMI, after=4),
                             P("Ticked by the person who did the work.", size=13, color=MUTED, ls=1.1)])
# column 3: question
icon(s, "circle-help_amber", 9.95, 1.98, 1.55)
T(s, 8.83, 4.25, 3.75, 1.2, [P("Requirements are assumed.", size=20, font=SEMI, after=4),
                             P("No one can show which photo proves which connection.", size=13, color=MUTED, ls=1.1)])
box(s, 0.75, 5.55, 11.83, 1.08, fill=PANEL, line=LINE, radius=0.18)
T(s, 1.0, 5.55, 4.9, 1.08, P("A cable is visible in a photo", size=20, font=LIGHT, color=MUTED, align="r"), anchor="m")
T(s, 6.0, 5.48, 1.33, 1.18, P("≠", size=44, color=BLUE, font=SEMI, align="c"), anchor="m")
T(s, 7.45, 5.55, 5.0, 1.08, P("The required connection is proven", size=20, font=SEMI), anchor="m")
footer(s, 2)
std_notes(s, 2, "ASSETS: three real photos from the final inspection (physical equipment) as ‘evidence photos’; the "
                "checklist is an illustrative generic site checklist (native shapes).")
transition(s, TIMING[2])

# ------------------------------------------------------------------------------------------------ 3 · insight
s = new_slide()
eyebrow(s, "THE INSIGHT")
title(s, "Seeing is not verifying.", size=44)
L = (0.75, 1.95, 5.55, 4.55)
Rr = (7.03, 1.95, 5.55, 4.55)
box(s, *L, fill=PANEL, line=LINE, radius=0.2)
box(s, *Rr, fill="0F1726", line=BLUE, lw=1.5, radius=0.2)
T(s, 1.05, 2.15, 5, 0.3, P("TRADITIONAL IMAGE AI", size=10.5, color=SUBTLE, font=SEMI, spc=1.8))
T(s, 1.05, 2.45, 5.0, 0.8, P("“What objects are in this photograph?”", size=19, font=LIGHT))
ix, iy, iw, ih = 1.05, 3.3, 3.45, 2.5875
pic(s, ph / "B1_photo.jpg", ix, iy, iw, ih, round_adj=4000, alt="Overview photo with illustrative object labels")
for (fx, fy, t) in [(0.12, 0.18, "television"), (0.64, 0.42, "game console"), (0.12, 0.8, "set-top box"), (0.42, 0.62, "cable")]:
    pill(s, ix + fx * iw, iy + fy * ih, 0.08 * len(t) + 0.32, 0.3, t, fg=TEXT, fill="0A0C10", line_c="C9D1DC", size=10, font=BODY, alpha=78)
T(s, 4.68, 3.35, 1.45, 2.4, [P("OUTPUT", size=9.5, color=SUBTLE, font=SEMI, spc=1.5, after=4), P("Labels.", size=22, font=SEMI, after=6),
                             P("No requirement checked. No gap found.", size=12, color=MUTED, ls=1.1)])
T(s, 1.05, 6.02, 4.9, 0.3, P("Illustrative labels on a real photo", size=9.5, color=SUBTLE))
T(s, 7.33, 2.15, 5, 0.3, P("PROOFCAM", size=10.5, color=BLUE, font=SEMI, spc=1.8))
T(s, 7.33, 2.45, 5.0, 0.85, P("“What evidence establishes that this requirement is satisfied?”", size=19, font=LIGHT))
pill(s, 7.33, 3.42, 4.95, 0.42, "R1 · set-top box RJ45  →  PS5 LAN  ·  Ethernet", fg=BLUE2, fill="0A0C10", line_c="2F4A7A", size=11.5, font=MONO, align="l")
rows = [("circle-check_green", "Set-top box RJ45 end", "photo 2 · Muse + SAM", GREEN),
        ("circle-check_green", "PS5 LAN end", "photo 4 · Muse + SAM", GREEN),
        ("circle-help_amber", "Same cable at both ends", "in no photo · gap stays open", AMBER)]
for i, (ic, a, b, col) in enumerate(rows):
    yy = 4.02 + i * 0.5
    icon(s, ic, 7.36, yy + 0.05, 0.3)
    T(s, 7.8, yy, 2.4, 0.42, P(a, size=14), anchor="m")
    T(s, 10.0, yy, 2.28, 0.42, P(b, size=11.5, color=col, align="r"), anchor="m")
T(s, 7.33, 5.62, 4.95, 0.7, [P("OUTPUT", size=9.5, color=SUBTLE, font=SEMI, spc=1.5, after=2),
                             P("Evidence, the open gap, and the next photo to take.", size=13, color=BLUE2)])
pill(s, 6.36, 3.95, 0.6, 0.6, "→", fg=TEXT, fill=BLUE, size=20)
T(s, 0.75, 6.66, 11.83, 0.36, P("From passive recognition to active evidence investigation.", size=15, color=MUTED, align="c"))
footer(s, 3)
std_notes(s, 3, "RIGHT PANEL VALUES: the real state of R1 in the final inspection after photo 4, before the operator's "
                "cable statement (both ends established from photos; cable identity shown in no photo, so the gap stayed "
                "open until the operator declared it).")
transition(s, TIMING[3])

# ------------------------------------------------------------------------------------------------ 4 · reveal
s = new_slide()
T(s, 0.75, 0.95, 5, 0.3, P("THE PRODUCT", size=11, color=BLUE, font=SEMI, spc=2.2))
T(s, 0.75, 1.25, 6.2, 1.0, P("Meet ProofCam.", size=50, font=SEMI))
T(s, 0.75, 2.25, 5.9, 0.9, P("An AI agent for evidence-driven physical inspections.", size=21, font=LIGHT, color=MUTED, ls=1.05))
steps = [("camera_blue", "Inspect", "Photograph the installation with any phone browser."),
         ("scan-search_blue", "Reason", "Muse Spark reads ports, plugs and labels; SAM 3.1 grounds them."),
         ("eye_blue", "Request", "It asks for the one view that closes the open gap."),
         ("shield-check_green", "Verify", "A deterministic policy decides, with an audit trail.")]
for i, (ic, a, b) in enumerate(steps):
    yy = 3.35 + i * 0.84
    icon(s, ic, 0.75, yy + 0.02, 0.46)
    T(s, 1.42, yy - 0.04, 5.0, 0.36, P(a, size=18, font=SEMI))
    T(s, 1.42, yy + 0.3, 5.0, 0.4, P(b, size=12.5, color=MUTED))
    if i < 3:
        line(s, 0.98, yy + 0.55, 0.98, yy + 0.8, color=LINE, w=1.25)
phone(s, 7.25, 0.5, 5.85, screen=ui / "landing_phone_screen.png", name="App screenshot · landing")
phone(s, 10.2, 0.75, 5.85, screen=ui / "B_phone_screen.png", name="App screenshot · completed inspection")
T(s, 7.25, 6.68, 5.6, 0.3, P("Real app screens (installable PWA) · start screen · completed real inspection",
                             size=9.5, color=SUBTLE, align="c"))
footer(s, 4)
std_notes(s, 4, "ASSETS: headless-Chrome captures of the real app (current build) showing the stored records; no new "
                "model calls. Right phone = the final real inspection (VERIFIED — operator-attested).")
transition(s, TIMING[4])

# ------------------------------------------------------------------------------------------------ 5 · demo A
s = new_slide()
_, (sx, sy, sw, sh) = video_placeholder(s, 0.75, 0.45, 6.6, "A", "VIOLATED INSPECTION", "≈20 s · router LAN 1 → switch port 3")
pill(s, sx + 0.18, sy + 0.25, sw - 0.36, 0.32, "▶▶ PROCESS ACCELERATED", fg="1A1204", fill=AMBER, size=9.5, spc=1,
     ).name = "CAPTION · PROCESS ACCELERATED (keep over sped-up footage)"
eyebrow(s, "LIVE DEMO  ·  RECORDING A", x=4.25)
title(s, "It doesn't approve everything.", x=4.25, w=8.3, size=36)
box(s, 4.25, 1.85, 4.05, 1.05, fill=PANEL, line=LINE, radius=0.14)
T(s, 4.45, 1.95, 3.7, 0.9, [P("REQUIREMENT", size=9.5, color=SUBTLE, font=SEMI, spc=1.5, after=3),
                            P("The blue Ethernet cable must connect Router LAN 1 to Switch Port 3.", size=13.5, ls=1.05)])
pic(s, ph / "A3_overlay.jpg", 4.25, 3.08, w=3.3, h=2.95, cover=True, round_adj=5000,
    alt="AI-generated test image of a router rear panel with ProofCam analysis overlay")
pill(s, 4.38, 3.2, 2.55, 0.32, "AI-GENERATED TEST IMAGE", fg="1A1204", fill=AMBER, size=9.5, spc=1)
T(s, 7.62, 3.12, 0.7, 2.9, [P("LAN 1", size=11, color=RED, font=SEMI), P("empty", size=11, color=RED, after=8),
                            P("plug", size=11, color=MUTED, font=SEMI), P("unlabelled socket", size=10, color=MUTED)])
T(s, 4.25, 6.15, 4.05, 0.7, P("“A model's observation is not enough. The requirement must be satisfied.”", size=14, font=LIGHT, ls=1.05))
pic(s, ui / "A_violated_card.png", 8.6, 1.85, w=3.98, alt="ProofCam violated verdict card (real app)")
T(s, 4.25, 7.02, 8.33, 0.3, P("Test photos are AI-generated (synthetic) and disclosed · analysed live by Meta Muse Spark 1.3 + SAM 3.1 · "
                              "3 photos · 5 model calls", size=9.5, color=SUBTLE))
std_notes(s, 5, """INSERT RECORDING A (VIOLATED):
1. Select the dashed frame ‘VIDEO PLACEHOLDER · RECORDING A’ (Home → Arrange → Selection Pane).
2. Insert → Video → This Device… → choose the (already sped-up) Recording A file. Drag it onto the frame, then right-click → Size and Position: Lock aspect ratio; height 6.45 in. Delete the dashed frame + label; keep the PHONE FRAME bezel and the PROCESS ACCELERATED pill (Bring to Front).
3. Playback tab: Start = Automatically; Volume = Mute; Trim Video to the strongest 20 s (see DEMO_TIMELINE.md).
4. Transitions → After = 19.5 s (the 20 s slot minus the 0.5 s fade; set a shorter clip accordingly).
CLIP PLAN (final-video time 0:37–0:57): requirement 1.5–2× · ‘Analysing…’ waits 6–8× (keep PROCESS ACCELERATED caption) · violated card 1× and hold ≥3 s.
FACTS: inspection insp_f1bb…, spec router_switch, 3 AI-generated test photos (IMG_6171–6173), 5 live calls (3 Muse, 2 SAM), VIOLATED because photo 3 legibly shows LAN 1 clearly empty; the blue plug sits in an unlabelled socket. The switch was never identified — that does not change the verdict.""")
transition(s, TIMING[5])

# ------------------------------------------------------------------------------------------------ 6 · loop
s = new_slide()
eyebrow(s, "HOW IT WORKS  ·  THE ACTIVE INSPECTION LOOP")
title(s, "ProofCam knows what it still needs to see.")
nodes = [("camera_blue", "Capture", "A photo from the phone camera"),
         ("scan-search_blue", "Observe", "Muse Spark: structured claims\nSAM 3.1: masks of each concept"),
         ("scale_blue", "Evaluate", "Policy re-assesses every requirement over all photos"),
         ("circle-help_amber", "Find the gap", "The most fundamental missing fact"),
         ("eye_blue", "Request a view", "Muse plans the next shot; fixed templates as fallback")]
for i, (ic, a, b) in enumerate(nodes):
    x = 0.75 + i * 2.4
    box(s, x, 1.95, 2.0, 1.85, fill=PANEL, line=LINE, radius=0.16)
    icon(s, ic, x + 0.2, 2.1, 0.42)
    T(s, x + 1.45, 2.1, 0.4, 0.3, P(f"0{i + 1}", size=10, color=SUBTLE, font=SEMI, align="r"))
    T(s, x + 0.2, 2.6, 1.7, 0.35, P(a, size=15, font=SEMI))
    T(s, x + 0.2, 2.93, 1.72, 0.84, P(b, size=10.5, color=MUTED, ls=1.05))
    if i < 4:
        line(s, x + 2.04, 2.87, x + 2.36, 2.87, color=BLUE, w=1.5, head="triangle")
line(s, 11.35, 3.8, 11.35, 4.17, color=BLUE, w=1.25)
line(s, 11.35, 4.17, 1.75, 4.17, color=BLUE, w=1.25)
line(s, 1.75, 4.17, 1.75, 3.85, color=BLUE, w=1.25, head="triangle")
pill(s, 3.55, 4.0, 6.0, 0.34, "repeat until every requirement has a verdict — or stop honestly",
     fg=MUTED, fill=BG, size=10.5, font=BODY)
cards = [("FROM THE REAL INSPECTION · REQUEST nv1 · PLANNED BY MUSE SPARK 1.3", BLUE,
          "Missing: the set-top box's connection ports have not been seen.",
          "“Walk around to behind the blue table and photograph the rear panel of the dark set-top box on the left…”",
          "Photo 2 → RJ45 plug seen by Muse, corroborated by SAM  ✓", GREEN),
         ("FROM THE REAL INSPECTION · REQUEST nv5 · FIXED TEMPLATE", BLUE,
          "Missing: both HDMI ends show a plug, but no photo shows one cable joining them.",
          "“Step back so one photo shows the hdmi cable run between both endpoints, from one device to the other…”",
          "No such photo was taken → the operator declared it instead, and the verdict says so.", AMBER)]
for i, (hd, hc, miss, quote, res, rc) in enumerate(cards):
    x = 0.75 + i * 6.03
    box(s, x, 4.58, 5.8, 2.2, fill=PANEL, line=LINE, radius=0.16)
    T(s, x + 0.25, 4.7, 5.4, 0.3, P(hd, size=9, color=hc, font=SEMI, spc=0.8))
    T(s, x + 0.25, 5.02, 5.35, 0.5, P(miss, size=12.5, color=TEXT, ls=1.05))
    T(s, x + 0.25, 5.53, 5.35, 0.75, P(quote, size=11.5, color=MUTED, italic=True, ls=1.05))
    T(s, x + 0.25, 6.28, 5.35, 0.42, P(res, size=11.5, color=rc, font=SEMI))
footer(s, 6)
std_notes(s, 6, "REAL REQUEST TEXTS: nv1 and nv5 of inspection insp_92cc… (copied verbatim, shortened with …). nv5 was "
                "issued from the fixed templates after the operator statements; the HDMI cable identity was then declared "
                "by the operator rather than shown in a photo.")
transition(s, TIMING[6])

# ------------------------------------------------------------------------------------------------ 7 · meta models
s = new_slide()
eyebrow(s, "META AI MODELS")
title(s, "Two Meta models. One verification system.")
layers = [("scan-search_blue", BLUE, "MUSE SPARK 1.3  ·  REASONS",
           "Reads each photo into structured claims (devices, ports, labels, plugs, cables, certainty) and plans the "
           "next camera view for the open gap.", "structured JSON output · vision · next-view planning"),
          ("layers_blue", CYAN, "SAM 3.1  ·  GROUNDS",
           "Segments each named cable and device concept on the same image. A plug claim counts only where a real "
           "mask reaches that port.", "concept segmentation · independent spatial check"),
          ("scale_white", TEXT, "DETERMINISTIC POLICY  ·  VERIFIES",
           "Fuses every photo against the specification. It alone sets VERIFIED, VIOLATED or INSUFFICIENT EVIDENCE, "
           "with the provenance of each claim.", "no model output is ever a verdict")]
for i, (ic, col, name, desc, tags) in enumerate(layers):
    y = 1.95 + i * 1.55
    box(s, 0.75, y, 6.75, 1.28, fill=PANEL, line=LINE, radius=0.14)
    box(s, 0.75, y + 0.18, 0.07, 0.92, fill=col)
    icon(s, ic, 1.05, y + 0.22, 0.44)
    T(s, 1.7, y + 0.12, 5.6, 0.32, P(name, size=13.5, color=col, font=SEMI, spc=1))
    T(s, 1.7, y + 0.42, 5.65, 0.58, P(desc, size=11.5, color=TEXT, ls=1.05))
    T(s, 1.7, y + 0.98, 5.6, 0.26, P(tags, size=9.5, color=SUBTLE, font=MONO))
    if i < 2:
        line(s, 4.1, y + 1.3, 4.1, y + 1.53, color=MUTED, w=1.25, head="triangle")
pic(s, ph / "B4_overlay.jpg", 8.25, 1.85, w=3.6, h=4.8, round_adj=4500,
    alt="Stored ProofCam analysis overlay of the PS5 rear: SAM masks and Muse boxes")
pill(s, 8.42, 5.92, 1.6, 0.3, "filled · SAM 3.1 mask", fg=TEXT, fill="0A0C10", line_c=CYAN, size=9, font=BODY, alpha=85)
pill(s, 10.1, 5.92, 1.62, 0.3, "dashed · Muse claim", fg=TEXT, fill="0A0C10", line_c=AMBER, size=9, font=BODY, alpha=85)
T(s, 7.8, 6.7, 4.5, 0.28, P("Photo 4, stored overlay · LAN: Muse + SAM ✓ · HDMI OUT: Muse only", size=9.5, color=SUBTLE,
                            align="c"))
T(s, 0.75, 6.45, 6.9, 0.32, P("Not one ‘looks connected’ prompt: 22 model calls across 4 photos, each claim checked.",
                              size=11, color=MUTED))
footer(s, 7)
std_notes(s, 7, "WHY THIS IS MORE THAN ONE VISION CALL: Muse produces schema-validated claims and plans views; SAM "
                "independently segments named concepts; the policy only accepts a plug where both agree and the spec's "
                "rules hold. SAM confirms a region, never cable identity or connector type on its own (disclosed in "
                "reports). Call counts from the trace of insp_92cc….")
transition(s, TIMING[7])

# ------------------------------------------------------------------------------------------------ 8 · demo B
s = new_slide()
_, (sx, sy, sw, sh) = video_placeholder(s, 0.75, 0.45, 6.6, "B", "REAL EQUIPMENT · 4 PHOTOS", "≈25 s · photos 1→4 and results")
pill(s, sx + 0.18, sy + 0.25, sw - 0.36, 0.32, "▶▶ PROCESS ACCELERATED", fg="1A1204", fill=AMBER, size=9.5, spc=1,
     ).name = "CAPTION · PROCESS ACCELERATED (keep over sped-up footage)"
eyebrow(s, "LIVE DEMO  ·  RECORDING B", x=4.25)
title(s, "Watch the evidence accumulate.", x=4.25, w=8.3, size=36)
steps = [("B1_photo.jpg", "PHOTO 1 · OVERVIEW", "TV, PlayStation 5 and Jio set-top box identified",
          "set-top box ports not visible → first next-view request", MUTED),
         ("B2_photo.jpg", "PHOTO 2 · REQUESTED VIEW", "Set-top box rear: RJ45 plug clearly inserted",
          "Muse ✓ · SAM ✓ (generic ‘cable’ mask) · end established", GREEN),
         ("B3_photo.jpg", "PHOTO 3 · REQUESTED VIEW", "TV panel: plug in HDMI 1 (ARC)",
          "Muse ✓ · SAM ✓ (generic ‘cable’ mask) · end established", GREEN),
         ("B4_photo.jpg", "PHOTO 4 · REQUESTED VIEW", "PS5 rear: LAN plug and HDMI OUT plug",
          "LAN: Muse ✓ SAM ✓  ·  HDMI OUT: Muse only (SAM found no HDMI cable)", AMBER)]
for i, (img, lab, main, ev, col) in enumerate(steps):
    y = 1.9 + i * 1.18
    pic(s, ph / img, 4.25, y, w=1.3, h=0.98, cover=True, round_adj=7000, alt=lab)
    T(s, 5.78, y + 0.0, 6.8, 0.28, P(lab, size=9.5, color=BLUE, font=SEMI, spc=1.2))
    T(s, 5.78, y + 0.27, 6.8, 0.34, P(main, size=14))
    T(s, 5.78, y + 0.62, 6.8, 0.32, P(ev, size=11, color=col))
T(s, 4.25, 6.72, 8.33, 0.3, P("Real equipment · 4 photos · 22 live Meta model calls (8 Muse Spark 1.3, 14 SAM 3.1) · "
                              "model waits sped up in the recording", size=9.5, color=SUBTLE))
std_notes(s, 8, """INSERT RECORDING B — PART 1 (photos 1→4):
1. Select ‘VIDEO PLACEHOLDER · RECORDING B’ in the Selection Pane; Insert → Video → This Device… → the sped-up clip of photos 1–4; size to height 6.45 in over the frame; delete the dashed frame + label, keep the PHONE FRAME bezel and the PROCESS ACCELERATED pill on top (Arrange → Bring to Front).
2. Playback: Start Automatically · Mute · Trim to 25 s. Transitions → After = 24.5 s (25 s slot minus the 0.5 s fade).
CLIP PLAN (final-video time 1:24–1:49): see DEMO_TIMELINE.md — waits 6–8×, each Next-view card readable ≥2 s at 1–1.5×.
FACTS: inspection insp_92cc…, spec ps5_home_setup_assisted (operator-assisted template), physical equipment, 4 photos, 22 live calls. Ends established from photos: set-top box RJ45 (photo 2), TV HDMI 1 (ARC) (photo 3), PS5 LAN (photo 4). PS5 HDMI OUT: Muse saw the plug; SAM's ‘hdmi cable’ found nothing and the generic ‘cable’ mask did not corroborate it.""")
transition(s, TIMING[8])

# ------------------------------------------------------------------------------------------------ 9 · HITL
s = new_slide()
eyebrow(s, "ASSURANCE  ·  HUMAN IN THE LOOP")
title(s, "When the camera can't prove it, ProofCam says so.", size=34, w=8.0, h=1.0)
cols = [(0.75, "circle-check_green", GREEN, "ESTABLISHED FROM PHOTOS", "Muse observed · SAM corroborated · policy accepted",
         [("Set-top box RJ45 plug", "photo 2"), ("PlayStation 5 LAN plug", "photo 4"), ("TV HDMI input plug", "photo 3")]),
        (4.7, "user-check_blue", BLUE2, "CONFIRMED BY THE OPERATOR", "Recorded verbatim · time-stamped · labelled in the verdict",
         [("Ethernet run is one cable", "declared · no photo traced it"), ("HDMI run is one cable", "declared · no photo traced it"),
          ("PS5 HDMI OUT plug", "attested in writing · Muse saw it, SAM did not corroborate")])]
for x, ic, col, hd, sub, items in cols:
    box(s, x, 2.17, 3.75, 3.8, fill=PANEL, line=col, lw=1.0, radius=0.16)
    icon(s, ic, x + 0.22, 2.35, 0.36)
    T(s, x + 0.68, 2.32, 2.95, 0.45, P(hd, size=11, color=col, font=SEMI, spc=1.2), anchor="m")
    T(s, x + 0.22, 2.82, 3.35, 0.5, P(sub, size=10.5, color=MUTED, ls=1.05))
    for j, (a, b) in enumerate(items):
        yy = 3.4 + j * 0.84
        box(s, x + 0.22, yy + 0.06, 0.05, 0.6, fill=col)
        T(s, x + 0.4, yy, 3.2, 0.36, P(a, size=13.5, font=SEMI))
        T(s, x + 0.4, yy + 0.33, 3.2, 0.45, P(b, size=10.5, color=MUTED, ls=1.05))
pic(s, ui / "B_R2_card.png", 8.85, 1.72, w=3.73, alt="ProofCam R2 verdict card: operator-attested, statements listed")
T(s, 0.75, 6.12, 7.7, 0.85, P("When visual evidence runs out, ProofCam doesn't invent certainty. It records exactly what "
                              "the human confirmed.", size=17, font=LIGHT, ls=1.05))
footer(s, 9)
std_notes(s, 9, "EXACT RECORD (insp_92cc…): od1 cable_identity R1 (00:13:49), od2 endpoint_attestation R2 PS5 HDMI OUT "
                "(00:14:10, note “It’s correct”), od3 cable_identity R2 (00:14:19). R1 = VERIFIED operator-assisted; "
                "R2 = VERIFIED operator-attested. The right image is the real R2 card from the app.")
transition(s, TIMING[9])

# ------------------------------------------------------------------------------------------------ 10 · result
s = new_slide()
eyebrow(s, "THE RESULT")
title(s, "Every verdict has an evidence trail.")
pic(s, ui / "B_installation.png", 0.75, 1.9, w=4.55, alt="ProofCam installation summary: Verified — operator-attested")
box(s, 5.65, 1.9, 6.93, 4.32, fill="0D1015", line=LINE, radius=0.16)
T(s, 5.92, 2.03, 6.4, 0.3, P("GENERATED REPORT  ·  EXCERPT (CONDENSED)", size=9.5, color=SUBTLE, font=SEMI, spc=1.4))
rep = [("OVERALL  VERIFIED — OPERATOR-ATTESTED, NOT VISUALLY ESTABLISHED", AMBER), ("", TEXT),
       ("R1 Ethernet   VERIFIED — OPERATOR-ASSISTED", GREEN),
       ("  photo 2   set-top box RJ45   Muse + SAM (generic) + shape", MUTED),
       ("  photo 4   PS5 LAN            Muse + SAM", MUTED),
       ("  00:13:49  operator: Ethernet run is one cable", BLUE2), ("", TEXT),
       ("R2 HDMI       VERIFIED — OPERATOR-ATTESTED", AMBER),
       ("  photo 3   TV HDMI 1 (ARC)    Muse + SAM (generic) + shape", MUTED),
       ("  00:14:10  operator: PS5 HDMI OUT end attested in writing", BLUE2),
       ("  00:14:19  operator: HDMI run is one cable", BLUE2)]
T(s, 5.92, 2.4, 6.5, 3.75, [P(t or " ", size=11, color=c, font=MONO, ls=1.12) for t, c in rep])
chips = ["2 / 2 requirements verified", "3 of 4 connection ends from photos", "3 operator statements, time-stamped",
         "22 live Meta model calls · ≈ $0.13"]
for i, c in enumerate(chips):
    x = 0.75 + i * 2.99
    box(s, x, 6.38, 2.85, 0.56, fill=PANEL, line=LINE, radius=0.12)
    T(s, x + 0.1, 6.38, 2.65, 0.56, P(c, size=11, color=TEXT, font=SEMI, align="c"), anchor="m")
footer(s, 10)
std_notes(s, 10, "IMPORTANT: the overall label is VERIFIED — OPERATOR-ATTESTED (R2's PS5 HDMI OUT end rests on a written "
                 "attestation), not ‘independently verified’ and not merely ‘operator-assisted’. The excerpt condenses real "
                 "lines of the generated Markdown report (supporting items, provenance and statement times). Cost is the "
                 "app's list-price estimate from the trace.")
transition(s, TIMING[10])

# ------------------------------------------------------------------------------------------------ 11 · tech
s = new_slide()
eyebrow(s, "ENGINEERING")
title(s, "Built for evidence, not just predictions.")
pipe = [("smartphone_blue", "Phone camera · PWA", "React 19 · TypeScript · Vite · Tailwind"),
        ("network_blue", "FastAPI service", "Python · Pydantic · one photo = one step"),
        ("scan-search_blue", "Meta Model API", "Muse Spark 1.3 · SAM 3.1 (streamed)"),
        ("layers_blue", "Structured observations", "schema-validated claims: devices, ports, plugs"),
        ("eye_blue", "Grounding", "SAM masks ↔ Muse boxes, per port"),
        ("scale_blue", "Deterministic policy", "verdicts · gaps · assurance"),
        ("database_blue", "SQLite inspection record", "append-only evidence · resumable"),
        ("file-check_blue", "Auditable report", "JSON + Markdown · provenance per claim")]
xs = [0.75, 3.82, 6.89, 9.96]
for i, (ic, a, b) in enumerate(pipe):
    row, k = divmod(i, 4)
    x = xs[k] if row == 0 else xs[3 - k]
    y = 1.95 if row == 0 else 3.75
    box(s, x, y, 2.6, 1.2, fill=PANEL, line=LINE, radius=0.14)
    icon(s, ic, x + 0.18, y + 0.18, 0.36)
    T(s, x + 0.65, y + 0.14, 1.9, 0.42, P(a, size=12, font=SEMI, ls=0.95), anchor="m")
    T(s, x + 0.18, y + 0.62, 2.3, 0.52, P(b, size=10, color=MUTED, ls=1.05))
for k in range(3):
    line(s, xs[k] + 2.62, 2.55, xs[k + 1] - 0.03, 2.55, color=BLUE, w=1.5, head="triangle")
    line(s, xs[k + 1] - 0.02, 4.35, xs[k] + 2.63, 4.35, color=BLUE, w=1.5, head="triangle")
line(s, xs[3] + 1.3, 3.17, xs[3] + 1.3, 3.73, color=BLUE, w=1.5, head="triangle")
chips = ["Call budget reserved before every request", "Idempotent, resumable captures", "Contradictions surfaced, never resolved silently",
         "Operator statements append-only", "499 backend + 57 frontend automated tests", "Tests use mocked models: regression, not accuracy"]
for i, c in enumerate(chips):
    row, k = divmod(i, 3)
    x = 0.75 + k * 3.98
    pill(s, x, 5.3 + row * 0.62, 3.84, 0.46, c, fg=TEXT if i < 5 else MUTED, fill=PANEL2, line_c=LINE, size=11, font=BODY)
T(s, 0.75, 6.62, 11.8, 0.3, P("≈6,300 lines of Python engine · ≈4,100 lines of TypeScript UI · built 30 Oct – 4 Nov 2026",
                              size=10, color=SUBTLE, align="c"))
footer(s, 11)
std_notes(s, 11, "VERIFIED FACTS (5 Nov 2026): backend pytest 499 passed (1 live test deselected); frontend vitest 57 passed; "
                 "tsc clean; production build OK. Tests run against mocked Meta responses and recorded fixtures: they are "
                 "regression tests for policy correctness and failure cases, not accuracy benchmarks. Line counts: "
                 "backend/proofcam/*.py and frontend/src (TS/TSX).")
transition(s, TIMING[11])

# ------------------------------------------------------------------------------------------------ 12 · vision
s = new_slide()
eyebrow(s, "THE BIGGER OPPORTUNITY")
title(s, "Today, cables. Tomorrow, infrastructure.")
pill(s, 0.75, 1.68, 6.6, 0.32, "PRODUCT VISION · POTENTIAL APPLICATIONS, NOT CURRENT DEPLOYMENTS", fg="1A1204", fill=AMBER, size=9.5, spc=0.8)
tiles = [("server_white", "Data centres", "Is every server patched to the port in the drawing?"),
         ("radio-tower_white", "Telecom", "Is each feed on the right port of the right radio?"),
         ("factory_white", "Factories", "Is the sensor installed and cabled as specified?"),
         ("solar-panel_white", "Energy", "Are string connectors where the design says?"),
         ("wrench_white", "Field service", "Was the part replaced, and can we show it?")]
for i, (ic, a, b) in enumerate(tiles):
    x = 0.75 + i * 2.4
    box(s, x, 2.2, 2.2, 2.75, fill=PANEL, line=LINE, radius=0.16)
    icon(s, ic, x + 0.25, 2.45, 0.6)
    T(s, x + 0.25, 3.25, 1.8, 0.4, P(a, size=17, font=SEMI))
    T(s, x + 0.25, 3.7, 1.8, 1.15, P(b, size=12, color=MUTED, italic=True, ls=1.08))
flow = ["Physical requirement", "Evidence", "Verification", "Audit trail"]
for i, f in enumerate(flow):
    x = 0.75 + i * 3.1
    box(s, x, 5.38, 2.55, 0.75, fill="0F1726" if i else PANEL, line=BLUE, lw=1.25, radius=0.14)
    T(s, x, 5.38, 2.55, 0.75, P(f, size=15, font=SEMI, align="c"), anchor="m")
    if i < 3:
        line(s, x + 2.58, 5.755, x + 3.07, 5.755, color=BLUE, w=1.5, head="triangle")
T(s, 0.75, 6.32, 11.83, 0.36, P("Same loop. Different specifications.", size=14, color=MUTED, align="c"))
footer(s, 12)
std_notes(s, 12, "Say ‘could’ — these are illustrative questions for a product vision. ProofCam today inspects cable "
                 "connections between devices from phone photos; nothing here has been deployed or measured in these "
                 "settings.")
transition(s, TIMING[12])

# ------------------------------------------------------------------------------------------------ 13 · why
s = new_slide()
eyebrow(s, "WHY THIS MATTERS")
T(s, 0.75, 0.9, 11.8, 1.6, P("What if every physical installation could explain why it was trusted?", size=38, font=SEMI, ls=0.95))
pillars = [("eye_white", "Verifiable observations", "Every claim is tied to a photo and a model output."),
           ("circle-help_white", "Clear uncertainty", "Unknown stays unknown. ‘Insufficient evidence’ is an answer."),
           ("scale_white", "Traceable decisions", "A deterministic policy, not a model's opinion, sets the verdict."),
           ("user-check_blue", "Human accountability", "When people vouch, their words are recorded and labelled.")]
for i, (ic, a, b) in enumerate(pillars):
    x = 0.75 + i * 3.02
    box(s, x, 2.95, 2.78, 2.35, fill=PANEL, line=LINE, radius=0.16)
    icon(s, ic, x + 0.25, 3.18, 0.55)
    T(s, x + 0.25, 3.9, 2.4, 0.4, P(a, size=16, font=SEMI))
    T(s, x + 0.25, 4.32, 2.35, 0.95, P(b, size=12, color=MUTED, ls=1.08))
T(s, 0.75, 5.75, 11.83, 0.9, P("The value isn't naming objects. It's deciding what observable evidence supports a physical "
                               "requirement.", size=19, font=LIGHT, align="c", ls=1.05))
footer(s, 13)
std_notes(s, 13)
transition(s, TIMING[13])

# ------------------------------------------------------------------------------------------------ 14 · close
s = new_slide()
box(s, W / 2 - 0.45, 1.25, 0.9, 0.9, fill=BLUE, radius=0.22)
icon(s, "scan-search_white", W / 2 - 0.3, 1.4, 0.6)
T(s, 0, 2.38, W, 1.1, P("PROOFCAM", size=64, font=SEMI, align="c", spc=10))
T(s, 0, 3.45, W, 0.6, P("The verification layer for the physical world.", size=26, font=LIGHT, align="c"))
T(s, 0, 4.12, W, 0.45, P("AI that doesn't just see the physical world. It asks for the evidence needed to verify it.",
                         size=14, color=MUTED, italic=True, align="c"))
line(s, W / 2 - 1.0, 4.85, W / 2 + 1.0, 4.85, color=LINE, w=1)
T(s, 0, 5.05, W, 0.4, P("Built with Meta Muse Spark 1.3 and SAM 3.1", size=15, align="c"))
T(s, 0, 5.47, W, 0.42, P("github.com/dakshvatss/proofcam", size=17, color=BLUE, font=SEMI, align="c"))
T(s, 0, 5.95, W, 0.4, P("Daksh Vats  ·  Indie Developer Track  ·  Push the Frontier", size=13, color=MUTED, align="c"))
T(s, 0, 6.9, W, 0.3, P("Independent project, not affiliated with or endorsed by Meta.", size=9.5, color=SUBTLE, align="c"))
std_notes(s, 14, "Hold the URL on screen for the whole 8 s. Before exporting: the repository must be PUBLIC and pushed "
                 "(see SUBMISSION_FINAL_CHECKLIST.md).")
transition(s, TIMING[14], thru_black=True, spd="slow")

# ================================================================================================ appendix
def appendix_header(s, label, ttl):
    eyebrow(s, f"APPENDIX  ·  {label}", color=SUBTLE)
    title(s, ttl, size=32)


# A1 · originality
s = new_slide()
appendix_header(s, "ORIGINALITY", "What I built during the hackathon")
line(s, 0.95, 2.35, 12.4, 2.35, color=LINE, w=2)
marks = [("30–31 Oct", "M0", "Inspection loop, deterministic policy, Meta API client; live Muse + SAM validation on five reference scenarios"),
         ("2 Nov", "M1–M2.2", "Resumable agent state, SQLite store, FastAPI service; verdict hardening; next-view guidance and contradictions"),
         ("3 Nov", "M2.3–M3.3", "Grounding geometry; mobile camera PWA; private access and spending cap; live-inference readiness"),
         ("4 Nov", "M3.4–M3.9", "Three devices / two connections; view relevance; evidence provenance; operator-assisted inspections"),
         ("4–5 Nov", "Demos", "Live VIOLATED run (synthetic test photos) and live VERIFIED run on the real home setup")]
for i, (d, m, t) in enumerate(marks):
    x = 0.95 + i * 2.37
    box(s, x - 0.08, 2.27, 0.16, 0.16, fill=BLUE, radius=0.08)
    T(s, x - 0.1, 1.85, 2.2, 0.32, P(d, size=12, font=SEMI, color=BLUE2))
    T(s, x - 0.1, 2.6, 2.15, 0.3, P(m, size=12.5, font=SEMI))
    T(s, x - 0.1, 2.92, 2.15, 1.3, P(t, size=10.5, color=MUTED, ls=1.05))
box(s, 0.75, 4.45, 5.8, 2.3, fill=PANEL, line=GREEN, radius=0.16)
T(s, 1.0, 4.58, 5.4, 2.1, [P("BUILT IN THIS REPOSITORY", size=10.5, color=GREEN, font=SEMI, spc=1.2, after=6)] +
  [P("•  " + t, size=11.5, after=2, ls=1.05) for t in [
      "Agent loop: gap selection, next-view requests, attempt ceilings", "Deterministic verification policy and evidence provenance",
      "Muse/SAM orchestration, grounding geometry, SAM fallback", "SQLite persistence, budgets, idempotent captures, FastAPI",
      "Mobile PWA, reports, operator statements, test suites"]])
box(s, 6.78, 4.45, 5.8, 2.3, fill=PANEL, line=LINE, radius=0.16)
T(s, 7.03, 4.58, 5.4, 2.1, [P("USED, NOT BUILT", size=10.5, color=MUTED, font=SEMI, spc=1.2, after=6)] +
  [P("•  " + t, size=11.5, after=2, ls=1.05, color=MUTED) for t in [
      "Meta Muse Spark 1.3 and SAM 3.1 via the Meta Model API", "React, Vite, Tailwind CSS, Lucide icons",
      "FastAPI, Pydantic, SQLite, Pillow, NumPy", "Meta's official SAM output parser (meta_sam_parser)",
      "All 18 commits dated 30 Oct – 4 Nov 2026 (repository created 30 Oct)"]])
footer(s, 15)
notes(s, "Facts from git history and docs/PROGRESS.md. The first commit (30 Oct 09:36 IST) adds only .gitattributes; the "
         "Milestone 0 code commit follows at 10:03. Work after the last commit (assisted-template and attestation "
         "changes) must be committed and pushed before submission.")
transition(s, 12)

# A2 · evidence levels
s = new_slide()
appendix_header(s, "EVIDENCE MODEL", "How ProofCam labels what it knows")
rows = [("GROUNDED", GREEN, "Muse claim + SAM mask at the port + spec rules", "Counts as evidence"),
        ("SEEN BY MUSE ONLY", AMBER, "Every check met except SAM corroboration", "Recorded, never counted"),
        ("OPERATOR-CONFIRMED", BLUE2, "Plug seated · device identity · one cable (spec-permitted)", "Counts; verdict marked operator-assisted"),
        ("OPERATOR-ATTESTED", BLUE2, "A written statement where no photo establishes the end", "Counts; verdict marked operator-attested"),
        ("UNRESOLVED / CONTRADICTED", RED, "Missing, ambiguous or conflicting observations", "Blocks verification; review if contradictory")]
for i, (a, c, b, d) in enumerate(rows):
    y = 1.85 + i * 0.78
    box(s, 0.75, y, 11.83, 0.66, fill=PANEL, line=LINE, radius=0.12)
    box(s, 0.75, y + 0.1, 0.07, 0.46, fill=c)
    T(s, 1.0, y, 3.2, 0.66, P(a, size=12, color=c, font=SEMI, spc=0.8), anchor="m")
    T(s, 4.3, y, 4.9, 0.66, P(b, size=12, color=TEXT), anchor="m")
    T(s, 9.3, y, 3.1, 0.66, P(d, size=11.5, color=MUTED, align="r"), anchor="m")
T(s, 0.75, 5.85, 11.83, 0.9, [P("Verdicts: VERIFIED · VIOLATED · INSUFFICIENT EVIDENCE — set only by the deterministic policy.", size=13, after=4),
                              P("Assurance on a verdict: visual · spec assumption · operator-assisted · operator-attested. "
                                "Statements never override a contradicting photo.", size=12, color=MUTED)])
footer(s, 16)
notes(s, "Source: backend/proofcam/policy.py and evidence.py (RequirementAssessment.assurance, EndpointAssessment.candidates, "
         "OperatorDeclaration). Operator statements are available only in the operator-assisted template.")
transition(s, 12)

# A3 · limits
s = new_slide()
appendix_header(s, "HONEST LIMITS", "What ProofCam does not claim")
lims = [("Not certification", "Visually observable conditions only: no electrical safety, network connectivity, signal or regulatory claims."),
        ("Synthetic data is disclosed", "Recording A uses AI-generated test photos. Recording B uses photos of real equipment."),
        ("SAM recall is imperfect", "In recorded live runs SAM's ‘hdmi cable’ concept found nothing in 12 of 12 photos; a bounded generic ‘cable’ fallback is disclosed when used."),
        ("Cable identity across photos", "Similar cables in different photos are never joined. Without a single-photo trace, identity needs a declared, labelled statement."),
        ("Static installations", "All photos are assumed to show one unchanged configuration; physical changes must be declared."),
        ("Tests ≠ accuracy", "Automated tests check policy behaviour with mocked models; no accuracy benchmark has been run.")]
for i, (a, b) in enumerate(lims):
    row, k = divmod(i, 2)
    x, y = 0.75 + k * 6.03, 1.85 + row * 1.55
    box(s, x, y, 5.8, 1.35, fill=PANEL, line=LINE, radius=0.14)
    T(s, x + 0.25, y + 0.15, 5.3, 0.36, P(a, size=14.5, font=SEMI))
    T(s, x + 0.25, y + 0.52, 5.35, 0.8, P(b, size=11.5, color=MUTED, ls=1.06))
footer(s, 17)
notes(s, "Sources: README/report disclaimer; docs/META_API_FACTS.md (SAM recall counts); docs/DECISIONS.md D39–D40.")
transition(s, 12)


# A4/A5 · hidden alternates for landscape recordings
def alt_slide(letter, ttl, n):
    s = new_slide()
    s._element.set("show", "0")
    eyebrow(s, f"ALTERNATE LAYOUT (HIDDEN) · USE IF RECORDING {letter} IS LANDSCAPE")
    title(s, ttl, size=30)
    vw = 9.6
    vh = vw * 9 / 16
    x = (W - vw) / 2
    box(s, x, 1.55, vw, vh, fill="0E131B", line=BLUE, lw=1.5, radius=0.18, dash=MSO_LINE_DASH_STYLE.DASH,
        name=f"VIDEO PLACEHOLDER 16:9 · RECORDING {letter}")
    T(s, x, 1.55, vw, vh, [P("▶", size=40, color=BLUE, align="c", after=6),
                           P(f"INSERT RECORDING {letter} (16:9)", size=20, color=BLUE, font=SEMI, align="c", spc=1.2, after=4),
                           P("Unhide this slide and hide the portrait version", size=12, color=MUTED, align="c")], anchor="m")
    notes(s, f"Use only if Recording {letter} is landscape (e.g. a laptop screen capture). Slide Show → Hide Slide toggles "
             f"visibility. Copy the narration/timing from main slide {n}.")
    transition(s, TIMING[n])
    return s


alt_slide("A", "It doesn't approve everything.", 5)
alt_slide("B", "Watch the evidence accumulate.", 8)

out = PRES / "ProofCam_Meta_Global_AI_Hackathon.pptx"
prs.save(out)
print("saved", out, "slides:", len(prs.slides))
