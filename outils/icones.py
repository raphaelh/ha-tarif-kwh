"""Génère toutes les images de Tarif kWh à partir d'un seul dessin.

    python outils/icones.py brand  custom_components/tarif_kwh/brand   # Home Assistant
    python outils/icones.py web    <dossier>                           # favicon, icônes, logos README
    python outils/icones.py social <fichier.png> "<sous-titre>"         # aperçu GitHub / liens (1280×640)

Pillow seul ; police DejaVu Sans (paquet fonts-dejavu). Le dessin : carré bleu arrondi, éclair blanc,
pièce « € » jaune. Pour le favicon (16-48 px), la pièce est retirée (illisible) et l'éclair recentré.
"""

from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

S = 2048  # dessin en très grand, puis réduction (anticrénelage)
BLEU = (30, 99, 214, 255)
JAUNE = (255, 193, 7, 255)
ENCRE = (33, 33, 33, 255)
BLANC = (255, 255, 255, 255)
GRIS = (91, 100, 112, 255)
FOND_SOCIAL = (245, 248, 255, 255)
DEJAVU = "/usr/share/fonts/truetype/dejavu/"
GRAS = DEJAVU + "DejaVuSans-Bold.ttf"
NORMAL = DEJAVU + "DejaVuSans.ttf"
ECLAIR = [(58, 10), (24, 56), (44, 56), (36, 90), (72, 40), (51, 40), (62, 10)]  # repère 0-100


def icone(piece: bool = True, coins_arrondis: bool = True) -> Image.Image:
    im = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, S - 1, S - 1), radius=int(S * 0.22) if coins_arrondis else 0, fill=BLEU)
    k = S / 100
    decalage = -6 if piece else 0  # avec la pièce, l'éclair glisse à gauche
    d.polygon([((x + decalage) * k, y * k) for x, y in ECLAIR], fill=BLANC)
    if piece:
        cx, cy, r = 72 * k, 72 * k, 21 * k
        d.ellipse((cx - r - 3 * k, cy - r - 3 * k, cx + r + 3 * k, cy + r + 3 * k), fill=BLEU)
        d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=JAUNE)
        d.text((cx, cy), "€", font=ImageFont.truetype(GRAS, int(30 * k)), fill=ENCRE, anchor="mm")
    return im


def logo(couleur_texte) -> Image.Image:
    ic = icone()
    police = ImageFont.truetype(GRAS, int(S * 0.62))
    gauche, _, droite, _ = police.getbbox("Tarif kWh", anchor="lm")
    marge = int(S * 0.22)
    im = Image.new("RGBA", (S + marge + (droite - gauche), S), (0, 0, 0, 0))
    im.paste(ic, (0, 0), ic)
    ImageDraw.Draw(im).text((S + marge - gauche, S // 2), "Tarif kWh", font=police, fill=couleur_texte, anchor="lm")
    return im.crop(im.getbbox())


def reduire(im: Image.Image, hauteur: int) -> Image.Image:
    return im.resize((round(im.width * hauteur / im.height), hauteur), Image.LANCZOS)


def enregistrer(im: Image.Image, chemin: Path, hauteur: int) -> None:
    reduire(im, hauteur).save(chemin, optimize=True)


def brand(dossier: Path) -> None:
    """Images lues par Home Assistant ≥ 2026.3 dans custom_components/<domaine>/brand/."""
    dossier.mkdir(parents=True, exist_ok=True)
    ic = icone()
    for suffixe, h in (("", 256), ("@2x", 512)):
        enregistrer(ic, dossier / f"icon{suffixe}.png", h)
        enregistrer(logo(ENCRE), dossier / f"logo{suffixe}.png", h // 2)
        enregistrer(logo(BLANC), dossier / f"dark_logo{suffixe}.png", h // 2)


SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">
<rect width="100" height="100" rx="22" fill="#1e63d6"/>
<polygon points="{eclair}" fill="#fff"/>
<circle cx="72" cy="72" r="24" fill="#1e63d6"/><circle cx="72" cy="72" r="21" fill="#ffc107"/>
<text x="72" y="72" dy=".35em" text-anchor="middle" font-family="DejaVu Sans,Verdana,Arial,sans-serif"
 font-weight="bold" font-size="30" fill="#212121">€</text>
</svg>
"""


def web(dossier: Path) -> None:
    """Favicon (ICO + SVG), icône d'écran d'accueil, icônes du manifeste, logos clair/sombre."""
    dossier.mkdir(parents=True, exist_ok=True)
    grande = icone()
    # ICO : version sans pièce, lisible en 16 px.
    reduire(icone(piece=False), 256).save(dossier / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    eclair = " ".join(f"{x - 6},{y}" for x, y in ECLAIR)
    (dossier / "icon.svg").write_text(SVG.format(eclair=eclair), encoding="utf-8")
    # iOS arrondit lui-même les coins et refuse la transparence : carré plein.
    enregistrer(icone(coins_arrondis=False).convert("RGB"), dossier / "apple-touch-icon.png", 180)
    enregistrer(grande, dossier / "icon-192.png", 192)
    enregistrer(grande, dossier / "icon-512.png", 512)
    enregistrer(logo(ENCRE), dossier / "logo.png", 128)
    enregistrer(logo(BLANC), dossier / "logo-sombre.png", 128)


def social(chemin: Path, sous_titre: str) -> None:
    """Aperçu 1280×640 (réglages GitHub > Social preview, balise og:image). Marges larges : les sites rognent."""
    L, H = 1280, 640
    im = Image.new("RGBA", (L, H), FOND_SOCIAL)
    lg = reduire(logo(ENCRE), 150)
    im.paste(lg, ((L - lg.width) // 2, 170), lg)
    d = ImageDraw.Draw(im)
    police = ImageFont.truetype(NORMAL, 38)
    y = 400
    for ligne in sous_titre.split("\\n"):
        d.text((L // 2, y), ligne, font=police, fill=GRIS, anchor="mm")
        y += 54
    d.rectangle((0, H - 16, L, H), fill=BLEU)
    chemin.parent.mkdir(parents=True, exist_ok=True)
    im.convert("RGB").save(chemin, optimize=True)


if __name__ == "__main__":
    commande, cible, *reste = sys.argv[1:]
    {"brand": brand, "web": web, "social": social}[commande](Path(cible), *reste)
