"""Tarif kWh : prix du kWh du Tarif Bleu (TRVE), publiés par raphaelh/tarif-kwh."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import CONF_OPTION, reglages
from .coordinator import TarifKwhCoordinator

PLATFORMS = [Platform.SENSOR]

type TarifKwhConfigEntry = ConfigEntry[TarifKwhCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TarifKwhConfigEntry) -> bool:
    coordinator = TarifKwhCoordinator(hass, entry, reglages(entry)[CONF_OPTION])
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_recharger))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: TarifKwhConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _recharger(hass: HomeAssistant, entry: TarifKwhConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
