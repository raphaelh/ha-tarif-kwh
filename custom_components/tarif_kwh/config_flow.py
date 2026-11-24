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


def _schema(defauts: dict[str, Any]) -> vol.Schema:
    return vol.Schema(
        {
            vol.Required(CONF_OPTION, default=defauts.get(CONF_OPTION, "tempo")): _selecteur_option(),
            vol.Required(CONF_PUISSANCE, default=defauts.get(CONF_PUISSANCE, "6")): _selecteur_puissance(),
            vol.Optional(
                CONF_COULEUR_TEMPO, description={"suggested_value": defauts.get(CONF_COULEUR_TEMPO)}
            ): EntitySelector(EntitySelectorConfig(domain=["sensor", "select", "input_select"])),
            vol.Optional(
                CONF_POINTE_EJP, description={"suggested_value": defauts.get(CONF_POINTE_EJP)}
            ): EntitySelector(
                EntitySelectorConfig(domain=["binary_sensor", "sensor", "input_boolean", "input_select"])
            ),
            vol.Optional(
                CONF_HEURES_CREUSES, description={"suggested_value": defauts.get(CONF_HEURES_CREUSES)}
            ): TextSelector(),
        }
    )


def _erreurs(saisie: dict[str, Any]) -> dict[str, str]:
    erreurs: dict[str, str] = {}
    if saisie[CONF_PUISSANCE] not in PUISSANCES[saisie[CONF_OPTION]]:
        erreurs[CONF_PUISSANCE] = "puissance_invalide"
    texte = saisie.get(CONF_HEURES_CREUSES)
    if texte:
        try:
            grille.parse_plages(texte)
        except ValueError:
            erreurs[CONF_HEURES_CREUSES] = "plages_invalides"
    return erreurs


def _complet(saisie: dict[str, Any]) -> dict[str, Any]:
    """Toutes les clés présentes : une valeur vidée doit masquer l'ancienne."""
    return {
        CONF_OPTION: saisie[CONF_OPTION],
        CONF_PUISSANCE: saisie[CONF_PUISSANCE],
        CONF_COULEUR_TEMPO: saisie.get(CONF_COULEUR_TEMPO) or None,
        CONF_POINTE_EJP: saisie.get(CONF_POINTE_EJP) or None,
        CONF_HEURES_CREUSES: saisie.get(CONF_HEURES_CREUSES) or None,
    }


class TarifKwhConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        # Un seul contrat : le manifeste interdit une seconde entrée (single_config_entry).
        erreurs: dict[str, str] = {}
        if user_input is not None:
            erreurs = _erreurs(user_input)
            if not erreurs:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=TITRE, data=_complet(user_input))
        return self.async_show_form(step_id="user", data_schema=_schema(user_input or {}), errors=erreurs)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TarifKwhOptionsFlow()


class TarifKwhOptionsFlow(OptionsFlow):
    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        erreurs: dict[str, str] = {}
        if user_input is not None:
            erreurs = _erreurs(user_input)
            if not erreurs:
                return self.async_create_entry(data=_complet(user_input))
        courant = {**reglages(self.config_entry), **(user_input or {})}
        return self.async_show_form(step_id="init", data_schema=_schema(courant), errors=erreurs)
