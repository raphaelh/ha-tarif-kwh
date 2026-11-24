"""Lecture des tarifs publiés (une fois par jour, avec ETag)."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from . import grille
from .const import DOMAIN, INTERVALLE_LECTURE, URL_BASE

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

    async def _async_setup(self) -> None:
        """Recharge la dernière version enregistrée (utile si le réseau est coupé au démarrage)."""
        stocke = await self._store.async_load()
        if stocke and grille.valider(stocke.get("data"), self.option) is None:
            self._cache = stocke["data"]
            self._etag = stocke.get("etag")

    async def _async_update_data(self) -> dict[str, Any]:
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
        await self._store.async_save({"data": data, "etag": etag})
        return data

    def _repli(self, message: str, cause: Exception | None = None) -> dict[str, Any]:
        """Garde la dernière version valable ; sans elle, l'échec est remonté."""
        if self._cache is not None:
            _LOGGER.warning("%s ; dernière version connue conservée", message)
            return self._cache
        raise UpdateFailed(message) from cause
