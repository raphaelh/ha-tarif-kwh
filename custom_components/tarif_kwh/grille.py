"""Logique pure (sans Home Assistant) : choix de la grille et de la période.

Ce module ne dépend d'aucun import Home Assistant pour pouvoir être testé seul.
"""

from __future__ import annotations

from datetime import date, time
from typing import Any

SCHEMA_VERSION = 1

Plage = tuple[time, time]


def valider(data: Any, option: str) -> str | None:
    """Renvoie None si le fichier publié est exploitable, sinon la raison du refus."""
    if not isinstance(data, dict):
        return "le fichier n'est pas un objet JSON"
    if data.get("schema_version") != SCHEMA_VERSION:
        return f"schema_version {data.get('schema_version')!r} non pris en charge"
    if data.get("option") != option:
        return f"option {data.get('option')!r} au lieu de {option!r}"
    actuelle = data.get("actuelle")
    if not isinstance(actuelle, dict) or not isinstance(actuelle.get("puissances"), dict):
        return "grille actuelle absente"
    if not actuelle.get("date_effet"):
        return "date d'effet de la grille actuelle absente"
    return None


def _date_effet(grille: dict[str, Any]) -> date | None:
    try:
        return date.fromisoformat(grille["date_effet"])
    except (KeyError, TypeError, ValueError):
        return None


def grille_en_vigueur(data: dict[str, Any], jour: date) -> dict[str, Any] | None:
    """Grille applicable à `jour`, choisie d'après sa date d'effet.

    Le fichier contient la grille actuelle et, quand elle est connue, la prochaine :
    on prend la plus récente dont la date d'effet est atteinte, sans dépendre de
    l'heure de la dernière lecture réseau.
    """
    candidates = [g for g in (data.get("actuelle"), data.get("prochaine")) if isinstance(g, dict)]
    appliquables = [
        (d, g) for g in candidates if (d := _date_effet(g)) is not None and d <= jour
    ]
    if appliquables:
        return max(appliquables, key=lambda x: x[0])[1]
    actuelle = data.get("actuelle")
    return actuelle if isinstance(actuelle, dict) else None


def puissance(grille: dict[str, Any] | None, kva: str) -> dict[str, Any] | None:
    if not grille:
        return None
    return grille.get("puissances", {}).get(str(kva))


def prix_ttc(grille: dict[str, Any] | None, kva: str, periode: str) -> float | None:
    p = puissance(grille, kva)
    if not p:
        return None
    return p.get("prix_ttc", {}).get(periode)


def abonnement_ttc(grille: dict[str, Any] | None, kva: str) -> float | None:
    p = puissance(grille, kva)
    return p.get("abonnement_ttc") if p else None


def abonnement_ttc_mensuel(grille: dict[str, Any] | None, kva: str) -> float | None:
    p = puissance(grille, kva)
    return p.get("abonnement_ttc_mensuel") if p else None


def parse_plages(texte: str) -> list[Plage]:
    """« 22:00-06:00, 13:00-15:00 » -> [(22:00, 06:00), (13:00, 15:00)].

    Lève ValueError si le texte est mal formé.
    """
    plages: list[Plage] = []
    for morceau in texte.replace(";", ",").split(","):
        morceau = morceau.strip()
        if not morceau:
            continue
        debut, sep, fin = morceau.partition("-")
        if not sep:
            raise ValueError(f"plage invalide : {morceau!r}")
        try:
            plages.append((time.fromisoformat(debut.strip()), time.fromisoformat(fin.strip())))
        except ValueError as err:
            raise ValueError(f"plage invalide : {morceau!r}") from err
    return plages


def dans_plages(heure: time, plages: list[Plage]) -> bool:
    """Vrai si `heure` est dans une des plages (début inclus, fin exclue, minuit géré)."""
    for debut, fin in plages:
        if debut <= fin:
            if debut <= heure < fin:
                return True
        elif heure >= debut or heure < fin:
            return True
    return False


_COULEURS = {
    "bleu": "bleu",
    "blue": "bleu",
    "blanc": "blanc",
    "white": "blanc",
    "rouge": "rouge",
    "red": "rouge",
}


def normaliser_couleur(etat: str | None) -> str | None:
    """Ramène l'état d'une entité Tempo (« bleu », « Blue », « blanc »…) à bleu/blanc/rouge."""
    if not etat:
        return None
    texte = etat.strip().lower()
    for mot, couleur in _COULEURS.items():
        if mot in texte:
            return couleur
    return None


_VRAI = {"on", "true", "oui", "yes", "pointe", "1"}
_FAUX = {"off", "false", "non", "no", "normal", "0"}


def normaliser_pointe(etat: str | None) -> bool | None:
    """État d'une entité « jour de pointe EJP » -> True / False, None si inconnu."""
    if not etat:
        return None
    texte = etat.strip().lower()
    if texte in _VRAI:
        return True
    if texte in _FAUX:
        return False
    return None


def periode_courante(
    option: str,
    heure: time,
    *,
    couleur: str | None = None,
    plages_hc: list[Plage] | None = None,
    plages_tempo_hc: list[Plage] | None = None,
    jour_pointe: bool | None = False,
    plages_pointe: list[Plage] | None = None,
) -> str | None:
    """Période tarifaire à l'instant donné, ou None si elle est indéterminée."""
    if option == "base":
        return "base"
    if option == "hphc":
        if not plages_hc:
            return None
        return "hc" if dans_plages(heure, plages_hc) else "hp"
    if option == "tempo":
        if couleur is None or not plages_tempo_hc:
            return None
        suffixe = "hc" if dans_plages(heure, plages_tempo_hc) else "hp"
        return f"{couleur}_{suffixe}"
    if option == "ejp":
        # jour_pointe None = entité configurée mais état inconnu : période indéterminée.
        if jour_pointe is None:
            return None
        return "pointe" if jour_pointe and dans_plages(heure, plages_pointe or []) else "normal"
    return None
