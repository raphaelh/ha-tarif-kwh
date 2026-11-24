"""Constantes de l'intégration Tarif kWh."""

from __future__ import annotations

from datetime import timedelta

DOMAIN = "tarif_kwh"

URL_BASE = "https://raphaelh.github.io/tarif-kwh"
SCHEMA_VERSION = 1

# Les tarifs ne changent que quelques fois par an : une lecture par jour suffit
# (avec ETag, GitHub Pages répond 304 sans corps tant que rien n'a changé).
INTERVALLE_LECTURE = timedelta(hours=24)
# Au-delà, alerte « prix peut-être plus à jour » : la collecte passe deux fois par jour.
SEUIL_DONNEES_ANCIENNES = timedelta(days=7)

CONF_OPTION = "option"
CONF_PUISSANCE = "puissance"
CONF_COULEUR_TEMPO = "couleur_tempo"
CONF_HEURES_CREUSES = "heures_creuses"
CONF_POINTE_EJP = "pointe_ejp"

def reglages(entry) -> dict:
    """Réglages du contrat : les options (modifiées dans « Configurer ») priment sur la saisie initiale."""
    return {**entry.data, **entry.options}


OPTIONS = {
    "base": "Base",
    "hphc": "Heures pleines / creuses",
    "tempo": "Tempo",
    "ejp": "EJP",
}

# Puissances (kVA) présentes dans les fichiers publiés, par option.
PUISSANCES = {
    "base": ("3", "6", "9", "12", "15", "18", "24", "30", "36"),
    "hphc": ("3", "6", "9", "12", "15", "18", "24", "30", "36"),
    "tempo": ("6", "9", "12", "15", "18", "24", "30", "36"),
    "ejp": ("9", "12", "15", "18", "36"),
}
TOUTES_PUISSANCES = ("3", "6", "9", "12", "15", "18", "24", "30", "36")

LIBELLES_PERIODES = {
    "base": "Base",
    "hp": "Heures pleines",
    "hc": "Heures creuses",
    "bleu_hc": "Bleu HC",
    "bleu_hp": "Bleu HP",
    "blanc_hc": "Blanc HC",
    "blanc_hp": "Blanc HP",
    "rouge_hc": "Rouge HC",
    "rouge_hp": "Rouge HP",
    "normal": "Normal",
    "pointe": "Pointe",
}

# Plages horaires fixes de l'option Tempo (HC 22h-6h).
PLAGES_TEMPO_HC = "22:00-06:00"

# Heures de pointe de l'option EJP, les jours de pointe mobile (07h à 01h).
PLAGES_EJP_POINTE = "07:00-01:00"
