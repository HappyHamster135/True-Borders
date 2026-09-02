# -*- coding: utf-8 -*-
"""Genererar ALLA Steam-butiksbilder för True Borders ur logokoncept A + E.

    python packaging/generate_steam_assets.py

Resultat i packaging/steam_assets/. Allt renderas i 2x och skalas ned med
LANCZOS för skarpa kanter. Kräver Montserrat-fonterna i packaging/fonts/
(hämtas från Google Fonts, se README-raden längst ner).

Koncept A ("Sikte"): fyra hörnklamrar + spelblocket i mitten — märket/ikonen.
Koncept E ("Ultrawide"): super-ultrawide skärm med spelet centrerat — motivet
i breda format (header, main capsule, library hero).
"""
import os

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "steam_assets")
FONTS = os.path.join(HERE, "fonts")
os.makedirs(OUT, exist_ok=True)

# ---- paletten (appens sage-tema) --------------------------------------------
SAGE = (143, 163, 97, 255)        # #8fa361 — klamrar/konturer
DEEP = (106, 122, 69, 255)        # #6a7a45 — spelblocket
CREAM = (240, 234, 212, 255)      # #f0ead4 — ordmärke/handtag
G_LIGHT = (43, 51, 36)            # bakgrundsgradient, ljus mitt
G_DARK = (20, 23, 15)             # bakgrundsgradient, mörk kant

F_XB = os.path.join(FONTS, "Montserrat-ExtraBold.ttf")
F_SB = os.path.join(FONTS, "Montserrat-SemiBold.ttf")


# ==============================================================================
# GRUNDER
# ==============================================================================

def ground(w, h, cx=0.32, cy=0.22):
    """Mörk sage-yta med mjuk radiell ljusning kring (cx, cy).

    Masken ditheras med svagt brus — annars blir 8-bitars-stegen i den
    uppskalade gradienten synliga som breda koncentriska bågar i stora
    format (library-heron är 3840 px bred)."""
    import os as _os

    from PIL import ImageChops

    img = Image.new("RGB", (w, h), G_LIGHT)
    dark = Image.new("RGB", (w, h), G_DARK)
    grad = Image.radial_gradient("L")            # 256x256, 0 i mitten -> 255 i kant
    big = max(w, h) * 3
    grad = grad.resize((big, big), Image.BILINEAR)
    mask = grad.crop((
        int(big / 2 - cx * w), int(big / 2 - cy * h),
        int(big / 2 - cx * w) + w, int(big / 2 - cy * h) + h,
    ))
    noise = Image.frombytes("L", (w, h), _os.urandom(w * h)).point(lambda v: v % 4)
    mask = ImageChops.add(mask, noise)
    img.paste(dark, (0, 0), mask)
    return img.convert("RGBA")


def mark_a(size, alpha=255):
    """Koncept A på transparent yta. Designraster 96."""
    s2 = size * 2
    k = s2 / 96.0
    img = Image.new("RGBA", (s2, s2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    sage = SAGE[:3] + (alpha,)
    deep = DEEP[:3] + (alpha,)

    def r(x, y, w, h, rad, fill):
        d.rounded_rectangle([x * k, y * k, (x + w) * k, (y + h) * k],
                            radius=rad * k, fill=fill)

    for x, y, w, h in [(8, 8, 30, 11), (8, 8, 11, 30),
                       (58, 8, 30, 11), (77, 8, 11, 30),
                       (8, 77, 30, 11), (8, 58, 11, 30),
                       (58, 77, 30, 11), (77, 58, 11, 30)]:
        r(x, y, w, h, 5.5, sage)
    r(31, 35, 34, 26, 4, deep)
    return img.resize((size, size), Image.LANCZOS)


def mark_e(width, alpha=255, handles=True):
    """Koncept E på transparent yta. Designraster 160x64."""
    w2 = width * 2
    k = w2 / 160.0
    h2 = int(64 * k)
    img = Image.new("RGBA", (w2, h2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    sage = SAGE[:3] + (alpha,)
    deep = DEEP[:3] + (alpha,)
    cream = CREAM[:3] + (alpha,)

    d.rounded_rectangle([5 * k, 7 * k, 155 * k, 57 * k], radius=11 * k,
                        outline=sage, width=max(2, int(round(5 * k))))
    d.rounded_rectangle([57 * k, 18 * k, 103 * k, 46 * k], radius=4 * k, fill=deep)
    if handles:
        for x, y in [(52, 13), (101, 13), (52, 44), (101, 44)]:
            d.rounded_rectangle([x * k, y * k, (x + 7) * k, (y + 7) * k],
                                radius=2 * k, fill=cream)
    return img.resize((width, int(h2 / 2)), Image.LANCZOS)


def tracked(draw, xy, text, font, fill, tracking):
    """Text med spärrning (letter-spacing) i pixlar. Returnerar bredden."""
    x, y = xy
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + tracking
    return x - tracking - xy[0]


def tracked_width(draw, text, font, tracking):
    return sum(draw.textlength(c, font=font) for c in text) + tracking * (len(text) - 1)


def wordmark(target, cx, top, size_big, gap=None):
    """TRUE (extrabold, cream) / BORDERS (semibold spärrad, sage), centrerat
    kring cx. Returnerar y-koordinaten under märket."""
    d = ImageDraw.Draw(target)
    f_big = ImageFont.truetype(F_XB, size_big)
    size_sub = int(size_big * 0.44)
    f_sub = ImageFont.truetype(F_SB, size_sub)
    tr_big = size_big * 0.10
    tr_sub = size_sub * 0.42

    w1 = tracked_width(d, "TRUE", f_big, tr_big)
    tracked(d, (cx - w1 / 2, top), "TRUE", f_big, CREAM, tr_big)
    y2 = top + int(size_big * 1.18)
    w2 = tracked_width(d, "BORDERS", f_sub, tr_sub)
    tracked(d, (cx - w2 / 2, y2), "BORDERS", f_sub, SAGE, tr_sub)
    return y2 + int(size_sub * 1.3)


def save(img, name, jpg=False):
    path = os.path.join(OUT, name)
    if jpg:
        img.convert("RGB").save(path, quality=92)
    else:
        img.save(path)
    print("skrev", name, img.size)


# ==============================================================================
# BILDERNA
# ==============================================================================

def compose_wide(w, h, e_width_frac, wm_frac):
    """Gemensam layout för breda kapslar: E-motivet överst, ordmärket under."""
    S = 2
    img = ground(w * S, h * S)
    e = mark_e(int(w * S * e_width_frac))
    total_h = e.height + int(h * S * 0.30)
    e_y = (h * S - total_h) // 2
    img.alpha_composite(e, ((w * S - e.width) // 2, e_y))
    wordmark(img, w * S / 2, e_y + e.height + int(h * S * 0.055), int(h * S * wm_frac))
    return img.resize((w, h), Image.LANCZOS)


def compose_tall(w, h, a_frac, wm_frac):
    """Gemensam layout för stående format: A-märket överst, ordmärket under."""
    S = 2
    img = ground(w * S, h * S, cx=0.5, cy=0.30)
    a = mark_a(int(w * S * a_frac))
    total_h = a.height + int(h * S * 0.185)
    a_y = (h * S - total_h) // 2
    img.alpha_composite(a, ((w * S - a.width) // 2, a_y))
    wordmark(img, w * S / 2, a_y + a.height + int(h * S * 0.045), int(w * S * wm_frac))
    return img.resize((w, h), Image.LANCZOS)


# --- Butik -------------------------------------------------------------------
save(compose_wide(920, 430, 0.62, 0.135), "header_capsule_920x430.png")
save(compose_wide(1232, 706, 0.66, 0.115), "main_capsule_1232x706.png")

# Small capsule: märket A till vänster, ordmärket till höger — fyller nästan
# hela ytan (Steams regel för small capsule).
S = 2
img = ground(462 * S, 174 * S, cx=0.22, cy=0.35)
a = mark_a(int(174 * S * 0.72))
img.alpha_composite(a, (int(462 * S * 0.055), (174 * S - a.height) // 2))
d = ImageDraw.Draw(img)
f_big = ImageFont.truetype(F_XB, int(174 * S * 0.30))
f_sub = ImageFont.truetype(F_SB, int(174 * S * 0.135))
tx = int(462 * S * 0.36)
ty = int(174 * S * 0.24)
tracked(d, (tx, ty), "TRUE", f_big, CREAM, 174 * S * 0.030)
tracked(d, (tx + int(174 * S * 0.012), ty + int(174 * S * 0.37)), "BORDERS", f_sub,
        SAGE, 174 * S * 0.056)
save(img.resize((462, 174), Image.LANCZOS), "small_capsule_462x174.png")

save(compose_tall(748, 896, 0.44, 0.105), "vertical_capsule_748x896.png")

# --- Bibliotek ---------------------------------------------------------------
save(compose_tall(600, 900, 0.50, 0.115), "library_capsule_600x900.png")
save(compose_wide(920, 430, 0.62, 0.135), "library_header_920x430.png")

# Library hero 3840x1240 — INGEN text; kärnan inom safe area 860x380 i mitten.
# Rent motiv: bara E-skärmen på gradienten. Steams logo-overlay (library_logo)
# läggs ändå ovanpå, så heron ska vara atmosfär — inte konkurrera.
S = 2
W, H = 3840 * S, 1240 * S
img = ground(3840 * S, 1240 * S, cx=0.5, cy=0.42)
e = mark_e(int(W * 0.56))
img.alpha_composite(e, ((W - e.width) // 2, (H - e.height) // 2))
save(img.resize((3840, 1240), Image.LANCZOS), "library_hero_3840x1240.png")

# Library logo — transparent PNG som Steam lägger ovanpå heron
S = 2
W, H = 1000 * S, 420 * S
img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
a = mark_a(int(H * 0.86))
img.alpha_composite(a, (int(H * 0.05), int(H * 0.07)))
d = ImageDraw.Draw(img)
f_big = ImageFont.truetype(F_XB, int(H * 0.30))
f_sub = ImageFont.truetype(F_SB, int(H * 0.135))
tx = int(H * 1.06)
ty = int(H * 0.20)
tracked(d, (tx, ty), "TRUE", f_big, CREAM, H * 0.030)
tracked(d, (tx + int(H * 0.012), ty + int(H * 0.37)), "BORDERS", f_sub, SAGE, H * 0.056)
save(img.resize((1000, 420), Image.LANCZOS), "library_logo_1000x420.png")

# --- App-administration ------------------------------------------------------
S = 2
img = ground(184 * S, 184 * S, cx=0.5, cy=0.40)
a = mark_a(int(184 * S * 0.74))
img.alpha_composite(a, ((184 * S - a.width) // 2, (184 * S - a.height) // 2))
save(img.resize((184, 184), Image.LANCZOS).convert("RGB"),
     "community_icon_184x184.jpg", jpg=True)

# Klient-ikon (32x32 .ico) + appens egen fleraupplösnings-ico
icon256 = mark_a(256)
icon256.save(os.path.join(OUT, "client_icon_32x32.ico"), sizes=[(32, 32)])
print("skrev client_icon_32x32.ico")
icon256.save(os.path.join(HERE, "trueborders.ico"),
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])
print("skrev trueborders.ico (16-256 px, för exe + tray)")

# En 64px PNG för tray-ikonen (bundlas av spec:arna)
mark_a(64).save(os.path.join(HERE, "tb_icon_64.png"))
print("skrev tb_icon_64.png")

print()
print("KLART ->", OUT)
print("Fonter: packaging/fonts/Montserrat-{SemiBold,ExtraBold}.ttf "
      "(Google Fonts, OFL-licens)")
