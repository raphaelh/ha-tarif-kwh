"""Capteurs : prix de chaque période, abonnement, date d'effet et prix actuel."""

from __future__ import annotations

from datetime import date
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from . import TarifKwhConfigEntry, grille
from .const import (
    CONF_COULEUR_TEMPO,
    CONF_HEURES_CREUSES,
    CONF_OPTION,
    CONF_POINTE_EJP,
    CONF_PUISSANCE,
    DOMAIN,
    LIBELLES_PERIODES,
    OPTIONS,
    PLAGES_EJP_POINTE,
    PLAGES_TEMPO_HC,
)
from .coordinator import TarifKwhCoordinator

UNITE_PRIX = "EUR/kWh"


async def async_setup_entry(
    hass: HomeAssistant, entry: TarifKwhConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    option = entry.data[CONF_OPTION]
    kva = entry.data[CONF_PUISSANCE]
    reglages = {**entry.data, **entry.options}

    entites: list[TarifKwhBase] = [
        PrixPeriode(coordinator, entry, kva, periode)
        for periode in coordinator.data.get("periodes", [])
    ]
    entites += [Abonnement(coordinator, entry, kva), DateEffet(coordinator, entry, kva)]

    couleur = reglages.get(CONF_COULEUR_TEMPO)
    heures_creuses = reglages.get(CONF_HEURES_CREUSES)
    pointe = reglages.get(CONF_POINTE_EJP)
    if option in ("base", "ejp") or (option == "tempo" and couleur) or (option == "hphc" and heures_creuses):
        entites.append(PrixActuel(coordinator, entry, kva, couleur or pointe, heures_creuses))
    async_add_entities(entites)


class TarifKwhBase(CoordinatorEntity[TarifKwhCoordinator], SensorEntity):
    """Base : appareil commun et recalcul à minuit (changement de grille à sa date d'effet)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: TarifKwhCoordinator, entry: TarifKwhConfigEntry, kva: str, cle: str) -> None:
        super().__init__(coordinator)
        self._kva = kva
        self._option = entry.data[CONF_OPTION]
        self._attr_unique_id = f"{entry.entry_id}_{cle}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="tarif-kwh (non officiel)",
            model=f"Tarif Bleu {OPTIONS[self._option]}",
            entry_type=DeviceEntryType.SERVICE,
            configuration_url="https://raphaelh.github.io/tarif-kwh/",
        )

    @property
    def _jour(self) -> date:
        return dt_util.now().date()

    @property
    def _grille(self) -> dict[str, Any] | None:
        return grille.grille_en_vigueur(self.coordinator.data, self._jour)

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_time_change(self.hass, self._minuit, hour=0, minute=0, second=1)
        )

    @callback
    def _minuit(self, _now: Any) -> None:
        self.async_write_ha_state()


class PrixPeriode(TarifKwhBase):
    _attr_translation_key = "prix"
    _attr_native_unit_of_measurement = UNITE_PRIX
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator, entry, kva: str, periode: str) -> None:
        super().__init__(coordinator, entry, kva, f"prix_{periode}")
        self._periode = periode
        self._attr_translation_placeholders = {"periode": LIBELLES_PERIODES.get(periode, periode)}

    @property
    def native_value(self) -> float | None:
        return grille.prix_ttc(self._grille, self._kva, self._periode)


class Abonnement(TarifKwhBase):
    _attr_translation_key = "abonnement"
    _attr_native_unit_of_measurement = "EUR/an"
    _attr_suggested_display_precision = 2

    def __init__(self, coordinator, entry, kva: str) -> None:
        super().__init__(coordinator, entry, kva, "abonnement")

    @property
    def native_value(self) -> float | None:
        return grille.abonnement_ttc(self._grille, self._kva)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"abonnement_ttc_mensuel": grille.abonnement_ttc_mensuel(self._grille, self._kva)}


class DateEffet(TarifKwhBase):
    _attr_translation_key = "date_effet"
    _attr_device_class = SensorDeviceClass.DATE
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, entry, kva: str) -> None:
        super().__init__(coordinator, entry, kva, "date_effet")

    @property
    def native_value(self) -> date | None:
        g = self._grille
        return date.fromisoformat(g["date_effet"]) if g else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        g = self._grille or {}
        return {"statut": g.get("statut"), "ttc_estime": g.get("ttc_estime")}


class PrixActuel(TarifKwhBase):
    """Prix TTC du kWh à l'instant, d'après l'heure (et la couleur Tempo ou le jour de pointe EJP)."""

    _attr_translation_key = "prix_actuel"
    _attr_native_unit_of_measurement = UNITE_PRIX
    _attr_suggested_display_precision = 4

    def __init__(self, coordinator, entry, kva: str, entite_suivie: str | None, heures_creuses: str | None) -> None:
        super().__init__(coordinator, entry, kva, "prix_actuel")
        self._entite_suivie = entite_suivie
        self._plages_hc = grille.parse_plages(heures_creuses) if heures_creuses else []
        self._plages_tempo = grille.parse_plages(PLAGES_TEMPO_HC)
        self._plages_pointe = grille.parse_plages(PLAGES_EJP_POINTE)
        self._periode: str | None = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(async_track_time_change(self.hass, self._tick, second=0))
        if self._entite_suivie:
            self.async_on_remove(
                async_track_state_change_event(self.hass, [self._entite_suivie], self._entite_changee)
            )

    @callback
    def _tick(self, _now: Any) -> None:
        self.async_write_ha_state()

    @callback
    def _entite_changee(self, _event: Event[EventStateChangedData]) -> None:
        self.async_write_ha_state()

    def _calculer_periode(self) -> str | None:
        couleur = None
        jour_pointe: bool | None = False  # EJP sans entité : jour normal supposé
        etat = self.hass.states.get(self._entite_suivie) if self._entite_suivie else None
        if self._option == "tempo" and self._entite_suivie:
            couleur = grille.normaliser_couleur(etat.state if etat else None)
        if self._option == "ejp" and self._entite_suivie:
            jour_pointe = grille.normaliser_pointe(etat.state if etat else None)
        return grille.periode_courante(
            self._option,
            dt_util.now().time(),
            couleur=couleur,
            plages_hc=self._plages_hc,
            plages_tempo_hc=self._plages_tempo,
            jour_pointe=jour_pointe,
            plages_pointe=self._plages_pointe,
        )

    @property
    def native_value(self) -> float | None:
        self._periode = self._calculer_periode()
        if self._periode is None:
            return None
        return grille.prix_ttc(self._grille, self._kva, self._periode)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        attributs: dict[str, Any] = {"periode": self._periode}
        if self._option == "ejp" and not self._entite_suivie:
            attributs["jours_de_pointe_suivis"] = False
        return attributs
