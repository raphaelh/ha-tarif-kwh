"""Configuration depuis l'interface : un seul contrat (option + puissance)."""

from __future__ import annotations

from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
)

from . import grille
from .const import (
    CONF_COULEUR_TEMPO,
    CONF_HEURES_CREUSES,
    CONF_OPTION,
    CONF_POINTE_EJP,
    CONF_PUISSANCE,
    DOMAIN,
    OPTIONS,
    PUISSANCES,
    TOUTES_PUISSANCES,
    reglages,
)

TITRE = "Tarif kWh"


def _selecteur_option() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[{"value": k, "label": v} for k, v in OPTIONS.items()],
            mode=SelectSelectorMode.DROPDOWN,
            translation_key="option",
        )
    )


def _selecteur_puissance() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=list(TOUTES_PUISSANCES),
            mode=SelectSelectorMode.DROPDOWN,
            translation_key="puissance",
        )
    )


# Le champ propre à chaque option, sur un second écran : Base n'en a pas.
CHAMP_PAR_OPTION = {"tempo": CONF_COULEUR_TEMPO, "ejp": CONF_POINTE_EJP, "hphc": CONF_HEURES_CREUSES}


def _schema_contrat(defauts: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_OPTION, default=defauts.get(CONF_OPTION, "tempo")): _selecteur_option(),
            vol.Required(CONF_PUISSANCE, default=defauts.get(CONF_PUISSANCE, "6")): _selecteur_puissance(),
        }
    )


def _selecteur_champ(champ: str):
    if champ == CONF_COULEUR_TEMPO:
        return EntitySelector(EntitySelectorConfig(domain=["sensor", "select", "input_select"]))
    if champ == CONF_POINTE_EJP:
        return EntitySelector(
            EntitySelectorConfig(domain=["binary_sensor", "sensor", "input_boolean", "input_select"])
        )
    return TextSelector()


def _schema_option(champ: str, defauts: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {vol.Optional(champ, description={"suggested_value": defauts.get(champ)}): _selecteur_champ(champ)}
    )


def _erreurs_contrat(saisie: dict[str, Any]) -> dict[str, str]:
    if saisie[CONF_PUISSANCE] not in PUISSANCES[saisie[CONF_OPTION]]:
        return {CONF_PUISSANCE: "puissance_invalide"}
    return {}


def _erreurs_option(saisie: dict[str, Any]) -> dict[str, str]:
    texte = saisie.get(CONF_HEURES_CREUSES)
    if texte:
        try:
            grille.parse_plages(texte)
        except ValueError:
            return {CONF_HEURES_CREUSES: "plages_invalides"}
    return {}


def _complet(contrat: dict[str, Any], saisie: dict[str, Any]) -> dict[str, Any]:
    """Toutes les clés présentes : seul le champ de l'option choisie est gardé, les autres sont vidés."""
    champ = CHAMP_PAR_OPTION.get(contrat[CONF_OPTION])
    donnees = {
        CONF_OPTION: contrat[CONF_OPTION],
        CONF_PUISSANCE: contrat[CONF_PUISSANCE],
        CONF_COULEUR_TEMPO: None,
        CONF_POINTE_EJP: None,
        CONF_HEURES_CREUSES: None,
    }
    if champ:
        donnees[champ] = saisie.get(champ) or None
    return donnees


class _Etapes:
    """Écran 1 : option et puissance ; écran 2 : le seul champ utile pour l'option choisie."""

    _contrat: dict[str, Any]

    def _defauts(self) -> dict[str, Any]:
        return {}

    def _terminer(self, donnees: dict[str, Any]) -> ConfigFlowResult:
        raise NotImplementedError

    async def _etape_contrat(self, step_id: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        erreurs: dict[str, str] = {}
        if user_input is not None:
            erreurs = _erreurs_contrat(user_input)
            if not erreurs:
                self._contrat = user_input
                if user_input[CONF_OPTION] not in CHAMP_PAR_OPTION:
                    return self._terminer(_complet(user_input, {}))
                return await getattr(self, f"async_step_{user_input[CONF_OPTION]}")()
        defauts = {**self._defauts(), **(user_input or {})}
        return self.async_show_form(step_id=step_id, data_schema=_schema_contrat(defauts), errors=erreurs)

    async def _etape_option(self, option: str, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        champ = CHAMP_PAR_OPTION[option]
        erreurs: dict[str, str] = {}
        if user_input is not None:
            erreurs = _erreurs_option(user_input)
            if not erreurs:
                return self._terminer(_complet(self._contrat, user_input))
        defauts = {**self._defauts(), **(user_input or {})}
        return self.async_show_form(step_id=option, data_schema=_schema_option(champ, defauts), errors=erreurs)

    async def async_step_tempo(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._etape_option("tempo", user_input)

    async def async_step_ejp(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._etape_option("ejp", user_input)

    async def async_step_hphc(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._etape_option("hphc", user_input)


class TarifKwhConfigFlow(_Etapes, ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        # Un seul contrat : le manifeste interdit une seconde entrée (single_config_entry).
        if user_input is not None:
            await self.async_set_unique_id(DOMAIN)
            self._abort_if_unique_id_configured()
        return await self._etape_contrat("user", user_input)

    def _terminer(self, donnees: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(title=TITRE, data=donnees)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TarifKwhOptionsFlow()


class TarifKwhOptionsFlow(_Etapes, OptionsFlow):
    def _defauts(self) -> dict[str, Any]:
        return reglages(self.config_entry)

    def _terminer(self, donnees: dict[str, Any]) -> ConfigFlowResult:
        return self.async_create_entry(data=donnees)

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return await self._etape_contrat("init", user_input)
