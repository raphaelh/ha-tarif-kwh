"""Lecture des tarifs publiés (une fois par jour, avec ETag)."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from . import grille
from .const import DOMAIN, INTERVALLE_LECTURE, SEUIL_DONNEES_ANCIENNES, URL_BASE

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1


class TarifKwhCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Récupère `<option>.json` ; garde la dernière version valable en cas d'échec."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, option: str) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"{DOMAIN}_{option}",
            update_interval=INTERVALLE_LECTURE,
        )
        self.option = option
        self.url = f"{URL_BASE}/{option}.json"
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, f"{DOMAIN}.{option}")
        self._etag: str | None = None
        self._cache: dict[str, Any] | None = None
        # etat.json du site : derniere_verification (renouvelée à chaque collecte réussie, deux fois
        # par jour) et l'état de publication de chaque option. Gardé avec la grille dans le Store.
        self.etat: dict[str, Any] | None = None

    async def _async_setup(self) -> None:
        """Recharge la dernière version enregistrée (utile si le réseau est coupé au démarrage)."""
        stocke = await self._store.async_load()
        if stocke and grille.valider(stocke.get("data"), self.option) is None:
            self._cache = stocke["data"]
            self._etag = stocke.get("etag")
            self.etat = stocke.get("etat")

    async def _async_update_data(self) -> dict[str, Any]:
        data = await self._lire_grille()
        await self._lire_etat()
        await self._store.async_save({"data": self._cache, "etag": self._etag, "etat": self.etat})
        self._signaler()
        return data

    async def _lire_grille(self) -> dict[str, Any]:
        session = async_get_clientsession(self.hass)
        entetes = {"If-None-Match": self._etag} if self._etag and self._cache else {}
        try:
            async with session.get(
                self.url, headers=entetes, timeout=aiohttp.ClientTimeout(total=30)
            ) as reponse:
                if reponse.status == 304 and self._cache is not None:
                    return self._cache
                reponse.raise_for_status()
                data = await reponse.json(content_type=None)
                etag = reponse.headers.get("ETag")
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            return self._repli(f"lecture de {self.url} impossible : {err}", err)

        refus = grille.valider(data, self.option)
        if refus:
            return self._repli(f"{self.url} inexploitable : {refus}")

        self._cache = data
        self._etag = etag
        return data

    async def _lire_etat(self) -> None:
        """Sans etat.json (réseau, format), on garde le dernier connu : il vieillit et finit par alerter."""
        url = f"{URL_BASE}/etat.json"
        try:
            async with async_get_clientsession(self.hass).get(url, timeout=aiohttp.ClientTimeout(total=30)) as reponse:
                reponse.raise_for_status()
                etat = await reponse.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOGGER.debug("lecture de %s impossible : %s", url, err)
            return
        if isinstance(etat, dict) and _date(etat.get("derniere_verification")):
            self.etat = etat

    @property
    def derniere_verification(self):
        return _date((self.etat or {}).get("derniere_verification"))

    @property
    def publication(self) -> str | None:
        return (((self.etat or {}).get("options") or {}).get(self.option) or {}).get("publication")

    def _signaler(self) -> None:
        """Alertes dans Paramètres > Réparations : source plus vérifiée, ou publication de l'option bloquée."""
        verif = self.derniere_verification
        if verif and dt_util.utcnow() - verif > SEUIL_DONNEES_ANCIENNES:
            ir.async_create_issue(
                self.hass, DOMAIN, "donnees_anciennes", is_fixable=False, severity=ir.IssueSeverity.WARNING,
                translation_key="donnees_anciennes",
                translation_placeholders={
                    "date": dt_util.as_local(verif).strftime("%d/%m/%Y"),
                    "jours": str((dt_util.utcnow() - verif).days),
                    "url": f"{URL_BASE}/",
                },
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, "donnees_anciennes")
        if self.publication not in (None, "ok"):
            ir.async_create_issue(
                self.hass, DOMAIN, "publication_bloquee", is_fixable=False, severity=ir.IssueSeverity.WARNING,
                translation_key="publication_bloquee",
                translation_placeholders={"option": self.option, "url": f"{URL_BASE}/etat.json"},
            )
        else:
            ir.async_delete_issue(self.hass, DOMAIN, "publication_bloquee")

    def _repli(self, message: str, cause: Exception | None = None) -> dict[str, Any]:
        """Garde la dernière version valable ; sans elle, l'échec est remonté."""
        if self._cache is not None:
            _LOGGER.warning("%s ; dernière version connue conservée", message)
            return self._cache
        raise UpdateFailed(message) from cause


def _date(texte: Any):
    return dt_util.parse_datetime(texte) if isinstance(texte, str) else None
