"""Capteurs : prix de chaque période, abonnement, date d'effet et prix actuel."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta
from functools import partial
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.core import Event, EventStateChangedData, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_change
from homeassistant.helpers.restore_state import ExtraStoredData, RestoredExtraData, RestoreEntity
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
    reglages,
)
from .coordinator import TarifKwhCoordinator

if TYPE_CHECKING:  # annotation seule : ce nom est absent de HA 2025.1 (version minimale)
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

_LOGGER = logging.getLogger(__name__)

UNITE_PRIX = "EUR/kWh"


async def async_setup_entry(
    hass: HomeAssistant, entry: TarifKwhConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    cfg = reglages(entry)
    option = cfg[CONF_OPTION]
    kva = cfg[CONF_PUISSANCE]

    entites: list[TarifKwhBase] = [
        PrixPeriode(coordinator, entry, kva, periode)
        for periode in coordinator.data.get("periodes", [])
    ]
    entites += [Abonnement(coordinator, entry, kva), DateEffet(coordinator, entry, kva)]

    couleur = cfg.get(CONF_COULEUR_TEMPO)
    heures_creuses = cfg.get(CONF_HEURES_CREUSES)
    pointe = cfg.get(CONF_POINTE_EJP)
    if option in ("base", "ejp") or (option == "tempo" and couleur) or (option == "hphc" and heures_creuses):
        entites.append(PrixActuel(coordinator, entry, kva, couleur or pointe, heures_creuses))
    _retirer_entites_obsoletes(hass, entry, {e.unique_id for e in entites})
    async_add_entities(entites)


def _retirer_entites_obsoletes(hass: HomeAssistant, entry: TarifKwhConfigEntry, gardees: set[str]) -> None:
    """Supprime les entités d'une ancienne option (changée dans « Configurer »)."""
    registre = er.async_get(hass)
    for e in er.async_entries_for_config_entry(registre, entry.entry_id):
        if e.unique_id not in gardees:
            registre.async_remove(e.entity_id)


class TarifKwhBase(CoordinatorEntity[TarifKwhCoordinator], SensorEntity):
    """Base : appareil commun et recalcul à minuit (changement de grille à sa date d'effet)."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, coordinator: TarifKwhCoordinator, entry: TarifKwhConfigEntry, kva: str, cle: str) -> None:
        super().__init__(coordinator)
        self._kva = kva
        cfg = reglages(entry)
        self._option = cfg[CONF_OPTION]
        self._attr_unique_id = f"{entry.entry_id}_{cle}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="tarif-kwh (non officiel)",
            model=f"Tarif Bleu {OPTIONS[self._option]} - {cfg[CONF_PUISSANCE]} kVA",
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
        return {
            "abonnement_ttc_mensuel": grille.abonnement_ttc_mensuel(self._grille, self._kva),
            "puissance_kva": self._kva,
        }


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


class PrixActuel(TarifKwhBase, RestoreEntity):
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
        # Dernière valeur valide de l'entité suivie, avec le jour auquel elle s'applique :
        # - EJP : jour de pointe (bool) du jour calendaire ;
        # - Tempo : couleur du jour Tempo (6h-6h).
        # Elle sert quand l'entité est indisponible, et à 0h-1h en EJP (tranche qui
        # appartient encore au jour de pointe de la veille).
        self._memoire: tuple[date, bool | str] | None = None

    @property
    def _suit_une_valeur(self) -> bool:
        return bool(self._entite_suivie) and self._option in ("tempo", "ejp")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._suit_une_valeur:
            await self._restaurer()
            await self._completer_par_historique()
        self.async_on_remove(async_track_time_change(self.hass, self._tick, second=0))
        if self._entite_suivie:
            self.async_on_remove(
                async_track_state_change_event(self.hass, [self._entite_suivie], self._entite_changee)
            )

    async def _restaurer(self) -> None:
        dernier = await self.async_get_last_extra_data()
        if not dernier:
            return
        try:
            brut = dernier.as_dict()
            valeur = brut.get("valeur", brut.get("pointe"))  # « pointe » : format de la v0.1.1
            if self._option == "ejp" and isinstance(valeur, bool):
                self._memoire = (date.fromisoformat(brut["date"]), valeur)
            elif self._option == "tempo" and valeur in ("bleu", "blanc", "rouge"):
                self._memoire = (date.fromisoformat(brut["date"]), valeur)
        except (KeyError, TypeError, ValueError):
            self._memoire = None

    def _fenetre(self) -> tuple[date, datetime, datetime]:
        """Jour dont on cherche la valeur, et fenêtre de l'historique où la chercher."""
        maintenant = dt_util.now()
        if self._option == "tempo":
            jour = (maintenant - timedelta(hours=6)).date()
            debut = datetime.combine(jour, time(6), tzinfo=maintenant.tzinfo)
            return jour, debut, maintenant
        jour = maintenant.date() if maintenant.hour >= 1 else maintenant.date() - timedelta(days=1)
        debut = datetime.combine(jour, time(1), tzinfo=maintenant.tzinfo)
        fin = min(datetime.combine(jour + timedelta(days=1), time(0), tzinfo=maintenant.tzinfo), maintenant)
        return jour, debut, fin

    async def _completer_par_historique(self) -> None:
        """Si la valeur du jour n'est pas connue (installation, redémarrage), la relire dans
        l'historique de l'enregistreur : dernier état exploitable de l'entité sur la période."""
        jour, debut, fin = self._fenetre()
        if self._memoire and self._memoire[0] == jour:
            return
        if "recorder" not in self.hass.config.components or fin <= debut:
            return
        try:
            from homeassistant.components.recorder import get_instance, history

            etats = await get_instance(self.hass).async_add_executor_job(
                partial(
                    history.get_significant_states,
                    self.hass,
                    debut,
                    fin,
                    [self._entite_suivie],
                    include_start_time_state=True,
                    significant_changes_only=False,
                    no_attributes=True,
                )
            )
        except Exception:  # noqa: BLE001 - l'historique est un plus : sans lui, on reste prudent
            _LOGGER.debug("Historique de %s illisible", self._entite_suivie, exc_info=True)
            return
        normaliser = grille.normaliser_couleur if self._option == "tempo" else grille.normaliser_pointe
        for etat in reversed(etats.get(self._entite_suivie, [])):
            valeur = normaliser(etat.state)
            if valeur is not None:
                self._memoire = (jour, valeur)
                return

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
            couleur = self._valeur_du_jour(grille.normaliser_couleur(etat.state if etat else None))
        if self._option == "ejp" and self._entite_suivie:
            jour_pointe = self._jour_pointe(grille.normaliser_pointe(etat.state if etat else None))
        return grille.periode_courante(
            self._option,
            dt_util.now().time(),
            couleur=couleur,
            plages_hc=self._plages_hc,
            plages_tempo_hc=self._plages_tempo,
            jour_pointe=jour_pointe,
            plages_pointe=self._plages_pointe,
        )

    def _valeur_du_jour(self, courante: Any) -> Any:
        """Valeur lue maintenant ; à défaut, la dernière valeur valide du même jour."""
        jour = self._fenetre()[0]
        if courante is not None:
            self._memoire = (jour, courante)
            return courante
        if self._memoire and self._memoire[0] == jour:
            return self._memoire[1]
        return None

    def _jour_pointe(self, courant: bool | None) -> bool | None:
        """Jour de pointe qui s'applique à l'instant, ou None si on ne le connaît pas.

        De 7h à 1h, c'est le jour de pointe du jour calendaire (l'entité). De 0h à 1h, la
        pointe est celle de la veille, retenue ou relue dans l'historique.
        """
        if dt_util.now().hour >= 1:
            return self._valeur_du_jour(courant)
        jour, _, _ = self._fenetre()  # la veille
        if self._memoire and self._memoire[0] == jour:
            return self._memoire[1]
        return None

    @property
    def extra_restore_state_data(self) -> ExtraStoredData | None:
        if self._memoire is None:
            return None
        return RestoredExtraData({"date": self._memoire[0].isoformat(), "valeur": self._memoire[1]})

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
