"""Configuration depuis l'interface."""

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
)


def _extras(defauts: dict[str, Any]) -> dict[Any, Any]:
    return {
        vol.Optional(
            CONF_COULEUR_TEMPO,
            description={"suggested_value": defauts.get(CONF_COULEUR_TEMPO)},
        ): EntitySelector(EntitySelectorConfig(domain=["sensor", "select", "input_select"])),
        vol.Optional(
            CONF_POINTE_EJP,
            description={"suggested_value": defauts.get(CONF_POINTE_EJP)},
        ): EntitySelector(
            EntitySelectorConfig(domain=["binary_sensor", "sensor", "input_boolean", "input_select"])
        ),
        vol.Optional(
            CONF_HEURES_CREUSES,
            description={"suggested_value": defauts.get(CONF_HEURES_CREUSES)},
        ): TextSelector(),
    }


def _erreurs(saisie: dict[str, Any]) -> dict[str, str]:
    erreurs: dict[str, str] = {}
    texte = saisie.get(CONF_HEURES_CREUSES)
    if texte:
        try:
            grille.parse_plages(texte)
        except ValueError:
            erreurs[CONF_HEURES_CREUSES] = "plages_invalides"
    return erreurs


def _nettoyer(saisie: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in saisie.items() if v not in (None, "")}


class TarifKwhConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        erreurs: dict[str, str] = {}
        if user_input is not None:
            option, kva = user_input[CONF_OPTION], user_input[CONF_PUISSANCE]
            if kva not in PUISSANCES[option]:
                erreurs[CONF_PUISSANCE] = "puissance_invalide"
            erreurs.update(_erreurs(user_input))
            if not erreurs:
                await self.async_set_unique_id(f"{option}_{kva}")
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=f"Tarif Bleu {OPTIONS[option]} {kva} kVA",
                    data=_nettoyer(user_input),
                )
        defauts = user_input or {}
        schema = vol.Schema(
            {
                vol.Required(CONF_OPTION, default=defauts.get(CONF_OPTION, "tempo")): SelectSelector(
                    SelectSelectorConfig(
                        options=[{"value": k, "label": v} for k, v in OPTIONS.items()],
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="option",
                    )
                ),
                vol.Required(CONF_PUISSANCE, default=defauts.get(CONF_PUISSANCE, "6")): SelectSelector(
                    SelectSelectorConfig(
                        options=list(TOUTES_PUISSANCES),
                        mode=SelectSelectorMode.DROPDOWN,
                        translation_key="puissance",
                    )
                ),
                **_extras(defauts),
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=erreurs)

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
                # Clés toujours présentes : une valeur vidée doit masquer celle de entry.data.
                return self.async_create_entry(
                    data={
                        CONF_COULEUR_TEMPO: user_input.get(CONF_COULEUR_TEMPO) or None,
                        CONF_POINTE_EJP: user_input.get(CONF_POINTE_EJP) or None,
                        CONF_HEURES_CREUSES: user_input.get(CONF_HEURES_CREUSES) or None,
                    }
                )
        courant = {**self.config_entry.data, **self.config_entry.options, **(user_input or {})}
        return self.async_show_form(
            step_id="init", data_schema=vol.Schema(_extras(courant)), errors=erreurs
        )
