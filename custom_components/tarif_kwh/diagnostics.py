"""Diagnostics téléchargeables (Paramètres > Appareils et services > Tarif kWh > ⋮ > Télécharger les diagnostics).

Rien de sensible : réglages du contrat, état de la dernière lecture et grilles reçues (sans le détail des puissances).
"""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import TarifKwhConfigEntry
from .const import reglages


def _resume_grille(g: dict[str, Any] | None) -> dict[str, Any] | None:
    if not g:
        return None
    return {
        "date_effet": g.get("date_effet"),
        "statut": g.get("statut"),
        "ttc_estime": g.get("ttc_estime"),
        "puissances": sorted(g.get("puissances", {}), key=int),
        "alertes": g.get("alertes"),
    }


async def async_get_config_entry_diagnostics(hass: HomeAssistant, entry: TarifKwhConfigEntry) -> dict[str, Any]:
    coordinator = entry.runtime_data
    data = coordinator.data or {}
    return {
        "reglages": reglages(entry),
        "lecture": {
            "url": coordinator.url,
            "derniere_reussie": coordinator.last_update_success,
            "derniere_erreur": str(coordinator.last_exception) if coordinator.last_exception else None,
            "etag": coordinator._etag,
        },
        "donnees": {
            "schema_version": data.get("schema_version"),
            "option": data.get("option"),
            "mis_a_jour_le": data.get("mis_a_jour_le"),
            "actuelle": _resume_grille(data.get("actuelle")),
            "prochaine": _resume_grille(data.get("prochaine")),
        },
    }
