"""Tests avec Home Assistant (pytest-homeassistant-custom-component)."""

import pytest
from aiohttp import ClientError
from homeassistant.config_entries import ConfigEntryState
from homeassistant.data_entry_flow import InvalidData
from homeassistant.helpers import entity_registry as er
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    async_fire_time_changed,
    mock_restore_cache_with_extra_data,
)
from homeassistant.core import State

from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.tarif_kwh.const import DOMAIN

URL = "https://raphaelh.github.io/tarif-kwh/tempo.json"
URL_ETAT = "https://raphaelh.github.io/tarif-kwh/etat.json"


@pytest.fixture(autouse=True)
def _custom(recorder_db_url, enable_custom_integrations):  # recorder_db_url avant hass
    yield


@pytest.fixture(autouse=True)
def etat_site(aioclient_mock):
    """etat.json du site, servi à chaque lecture ; par défaut vérifié à l'instant et publication « ok ».

    Un test le modifie (dict) pour simuler une source ancienne ou bloquée, ou met « exc » pour une panne.
    Il reste enregistré après aioclient_mock.clear_requests().
    """
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

    etat: dict = {"options": {"tempo": {"publication": "ok"}}}

    async def repondre(method, url, data):
        if "exc" in etat:
            return AiohttpClientMockResponse(method, url, exc=etat["exc"])
        corps = {"derniere_verification": dt_util.utcnow().isoformat(), **etat}
        return AiohttpClientMockResponse(method, url, json=corps)

    def enregistrer():
        aioclient_mock.get(URL_ETAT, side_effect=repondre)

    vider = aioclient_mock.clear_requests

    def clear_requests():
        vider()
        enregistrer()

    aioclient_mock.clear_requests = clear_requests
    enregistrer()
    return etat


def _appels(aioclient_mock, url=URL):
    return [c for c in aioclient_mock.mock_calls if str(c[1]) == url]


def _entree(**extra):
    return MockConfigEntry(
        domain=DOMAIN,
        title="Tarif kWh",
        unique_id=DOMAIN,
        data={"option": "tempo", "puissance": "6", **extra},
    )


def _etat(hass, entry, cle):
    reg = er.async_get(hass)
    entity_id = reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_{cle}")
    assert entity_id, f"entité {cle} absente"
    return hass.states.get(entity_id)


async def _installer(hass, entry):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_capteurs_prix(hass, aioclient_mock, tempo_json):
    aioclient_mock.get(URL, json=tempo_json, headers={"ETag": '"v1"'})
    entry = _entree()
    await _installer(hass, entry)
    p6 = tempo_json["actuelle"]["puissances"]["6"]
    assert float(_etat(hass, entry, "prix_bleu_hc").state) == p6["prix_ttc"]["bleu_hc"]
    assert float(_etat(hass, entry, "prix_rouge_hp").state) == p6["prix_ttc"]["rouge_hp"]
    assert float(_etat(hass, entry, "abonnement").state) == p6["abonnement_ttc"]
    assert len(_appels(aioclient_mock)) == 1


async def test_prix_actuel_tempo(hass, aioclient_mock, tempo_json, freezer):
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to("2026-11-23 11:00:00+00:00")  # 12h00 à Paris : heures pleines
    aioclient_mock.get(URL, json=tempo_json)
    hass.states.async_set("sensor.couleur_tempo", "Blanc")
    entry = _entree(couleur_tempo="sensor.couleur_tempo")
    await _installer(hass, entry)
    p6 = tempo_json["actuelle"]["puissances"]["6"]["prix_ttc"]
    etat = _etat(hass, entry, "prix_actuel")
    assert float(etat.state) == p6["blanc_hp"]
    assert etat.attributes["periode"] == "blanc_hp"

    hass.states.async_set("sensor.couleur_tempo", "rouge")
    await hass.async_block_till_done()
    assert float(_etat(hass, entry, "prix_actuel").state) == p6["rouge_hp"]

    freezer.move_to("2026-11-23 22:30:00+00:00")  # 23h30 à Paris : heures creuses
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert float(_etat(hass, entry, "prix_actuel").state) == p6["rouge_hc"]

    # Entité indisponible : la couleur ne change pas pendant le jour Tempo, on garde la dernière.
    hass.states.async_set("sensor.couleur_tempo", "unavailable")
    await hass.async_block_till_done()
    assert float(_etat(hass, entry, "prix_actuel").state) == p6["rouge_hc"]


async def test_pas_de_prix_actuel_sans_couleur(hass, aioclient_mock, tempo_json):
    aioclient_mock.get(URL, json=tempo_json)
    entry = _entree()
    await _installer(hass, entry)
    reg = er.async_get(hass)
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_prix_actuel") is None


async def test_lecture_conditionnelle_et_repli(hass, aioclient_mock, tempo_json):
    aioclient_mock.get(URL, json=tempo_json, headers={"ETag": '"v1"'})
    entry = _entree()
    await _installer(hass, entry)
    coordinator = entry.runtime_data

    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, status=304)
    await coordinator.async_refresh()
    assert coordinator.last_update_success
    assert _appels(aioclient_mock)[-1][3]["If-None-Match"] == '"v1"'
    assert coordinator.data == tempo_json

    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, exc=ClientError("coupé"))
    await coordinator.async_refresh()
    assert coordinator.last_update_success  # dernière version conservée
    assert coordinator.data == tempo_json

    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, json={"schema_version": 99})
    await coordinator.async_refresh()
    assert coordinator.data == tempo_json


async def test_echec_sans_cache_reessaie(hass, aioclient_mock):
    aioclient_mock.get(URL, exc=ClientError("coupé"))
    entry = _entree()
    entry.add_to_hass(hass)
    assert not await hass.config_entries.async_setup(entry.entry_id)
    assert entry.state is ConfigEntryState.SETUP_RETRY


async def test_demarrage_hors_ligne_avec_cache(hass, aioclient_mock, tempo_json):
    aioclient_mock.get(URL, json=tempo_json, headers={"ETag": '"v1"'})
    entry = _entree()
    await _installer(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)

    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, exc=ClientError("coupé"))
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert entry.state is ConfigEntryState.LOADED
    assert _etat(hass, entry, "prix_bleu_hc").state != "unavailable"


async def test_config_flow(hass):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert r["type"] == "form"

    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"option": "ejp", "puissance": "6"})
    assert r["errors"] == {"puissance": "puissance_invalide"}

    # Premier écran : option et puissance seulement.
    assert set(r["data_schema"].schema) == {"option", "puissance"}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"option": "hphc", "puissance": "9"})
    # Second écran : le seul champ utile pour HP/HC.
    assert r["type"] == "form" and r["step_id"] == "hphc"
    assert set(r["data_schema"].schema) == {"heures_creuses"}

    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"heures_creuses": "22h-6h"})
    assert r["errors"] == {"heures_creuses": "plages_invalides"}

    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"heures_creuses": "22:00-06:00"})
    assert r["type"] == "create_entry"
    assert r["title"] == "Tarif kWh"
    assert r["data"] == {
        "option": "hphc", "puissance": "9", "couleur_tempo": None, "pointe_ejp": None,
        "heures_creuses": "22:00-06:00",
    }

    # Un seul contrat : une seconde entrée est refusée.
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert r["type"] == "abort"
    assert r["reason"] == "single_instance_allowed"


async def test_config_flow_base_un_seul_ecran(hass):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"option": "base", "puissance": "6"})
    assert r["type"] == "create_entry"
    assert r["data"] == {"option": "base", "puissance": "6", "couleur_tempo": None, "pointe_ejp": None, "heures_creuses": None}


@pytest.mark.parametrize(
    ("option", "puissance", "champ", "valeur"),
    [("tempo", "18", "couleur_tempo", "sensor.couleur_tempo"), ("ejp", "9", "pointe_ejp", "binary_sensor.ejp")],
)
async def test_config_flow_second_ecran(hass, option, puissance, champ, valeur):
    r = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {"option": option, "puissance": puissance})
    assert r["step_id"] == option
    assert set(r["data_schema"].schema) == {champ}
    r = await hass.config_entries.flow.async_configure(r["flow_id"], {champ: valeur})
    assert r["type"] == "create_entry"
    attendu = {"option": option, "puissance": puissance, "couleur_tempo": None, "pointe_ejp": None, "heures_creuses": None}
    attendu[champ] = valeur
    assert r["data"] == attendu


async def test_options_flow_vider_un_reglage(hass, aioclient_mock, tempo_json):
    aioclient_mock.get(URL, json=tempo_json)
    entry = _entree(couleur_tempo="sensor.couleur_tempo")
    await _installer(hass, entry)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"option": "tempo", "puissance": "6"})
    assert r["step_id"] == "tempo"
    # La valeur actuelle est proposée ; l'utilisateur la vide.
    cle = next(iter(r["data_schema"].schema))
    assert cle.description == {"suggested_value": "sensor.couleur_tempo"}
    r = await hass.config_entries.options.async_configure(r["flow_id"], {})
    assert r["type"] == "create_entry"
    assert r["data"] == {"option": "tempo", "puissance": "6", "couleur_tempo": None, "pointe_ejp": None, "heures_creuses": None}
    await hass.async_block_till_done()
    assert {**entry.data, **entry.options}["couleur_tempo"] is None


async def test_prix_actuel_ejp_sans_entite(hass, aioclient_mock, ejp_json, freezer):
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to("2026-11-23 11:00:00+00:00")  # 12h00 à Paris
    aioclient_mock.get("https://raphaelh.github.io/tarif-kwh/ejp.json", json=ejp_json)
    p9 = ejp_json["actuelle"]["puissances"]["9"]["prix_ttc"]
    # Sans entité : prix normal, signalé dans les attributs.
    sans = MockConfigEntry(domain=DOMAIN, title="Tarif kWh", unique_id=DOMAIN, data={"option": "ejp", "puissance": "9"})
    await _installer(hass, sans)
    etat = _etat(hass, sans, "prix_actuel")
    assert float(etat.state) == p9["normal"]
    assert etat.attributes["jours_de_pointe_suivis"] is False


async def test_prix_actuel_ejp_avec_entite(hass, aioclient_mock, ejp_json, freezer):
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to("2026-11-23 11:00:00+00:00")  # 12h00 à Paris
    aioclient_mock.get("https://raphaelh.github.io/tarif-kwh/ejp.json", json=ejp_json)
    # Avec entité : pointe de 7h à 1h les jours de pointe.
    hass.states.async_set("binary_sensor.ejp_pointe", "on")
    avec = _ejp_avec_entite()
    await _installer(hass, avec)
    p12 = ejp_json["actuelle"]["puissances"]["12"]["prix_ttc"]
    assert float(_etat(hass, avec, "prix_actuel").state) == p12["pointe"]

    hass.states.async_set("binary_sensor.ejp_pointe", "off")
    await hass.async_block_till_done()
    assert float(_etat(hass, avec, "prix_actuel").state) == p12["normal"]

    # Entité indisponible : l'indicateur ne change pas dans la journée, on garde le dernier.
    hass.states.async_set("binary_sensor.ejp_pointe", "unavailable")
    await hass.async_block_till_done()
    assert float(_etat(hass, avec, "prix_actuel").state) == p12["normal"]


def _ejp_avec_entite(**extra):
    return MockConfigEntry(
        domain=DOMAIN, title="Tarif kWh", unique_id=DOMAIN,
        data={"option": "ejp", "puissance": "12", "pointe_ejp": "binary_sensor.ejp_pointe", **extra},
    )


async def test_ejp_tranche_0h_1h_suit_la_veille(hass, aioclient_mock, ejp_json, freezer):
    """0h-1h appartient au jour de pointe de la veille, même si l'entité a basculé à minuit."""
    await hass.config.async_set_time_zone("Europe/Paris")
    aioclient_mock.get("https://raphaelh.github.io/tarif-kwh/ejp.json", json=ejp_json)
    p = ejp_json["actuelle"]["puissances"]["12"]["prix_ttc"]
    freezer.move_to("2026-11-23 22:30:00+00:00")  # 23h30 à Paris
    hass.states.async_set("binary_sensor.ejp_pointe", "on")
    entry = _ejp_avec_entite()
    await _installer(hass, entry)
    assert float(_etat(hass, entry, "prix_actuel").state) == p["pointe"]

    # Minuit passé : l'entité indique le nouveau jour (normal), mais 0h30 reste en pointe.
    freezer.move_to("2026-11-23 23:30:00+00:00")  # 0h30 le 24
    hass.states.async_set("binary_sensor.ejp_pointe", "off")
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert float(_etat(hass, entry, "prix_actuel").state) == p["pointe"]

    freezer.move_to("2026-11-24 00:30:00+00:00")  # 1h30 : normal
    async_fire_time_changed(hass)
    await hass.async_block_till_done()
    assert float(_etat(hass, entry, "prix_actuel").state) == p["normal"]


async def test_ejp_0h_1h_apres_redemarrage(hass, aioclient_mock, ejp_json, freezer):
    """Un redémarrage à 0h30 retrouve la veille grâce à la valeur restaurée ; sans elle : inconnu."""
    await hass.config.async_set_time_zone("Europe/Paris")
    aioclient_mock.get("https://raphaelh.github.io/tarif-kwh/ejp.json", json=ejp_json)
    p = ejp_json["actuelle"]["puissances"]["12"]["prix_ttc"]
    freezer.move_to("2026-11-23 23:30:00+00:00")  # 0h30 le 24
    hass.states.async_set("binary_sensor.ejp_pointe", "off")
    entry = _ejp_avec_entite()
    entry.add_to_hass(hass)
    reg = er.async_get(hass)
    reg.async_get_or_create(
        "sensor", DOMAIN, f"{entry.entry_id}_prix_actuel", suggested_object_id="ejp_prix_actuel",
        config_entry=entry,
    )
    mock_restore_cache_with_extra_data(
        hass,
        [(State("sensor.ejp_prix_actuel", "0.1"), {"date": "2026-11-23", "pointe": True})],
    )
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert float(_etat(hass, entry, "prix_actuel").state) == p["pointe"]


async def test_ejp_0h_1h_sans_observation_inconnu(hass, aioclient_mock, ejp_json, freezer):
    await hass.config.async_set_time_zone("Europe/Paris")
    aioclient_mock.get("https://raphaelh.github.io/tarif-kwh/ejp.json", json=ejp_json)
    freezer.move_to("2026-11-23 23:30:00+00:00")  # 0h30 le 24, rien d'observé la veille
    hass.states.async_set("binary_sensor.ejp_pointe", "on")
    entry = _ejp_avec_entite()
    await _installer(hass, entry)
    assert _etat(hass, entry, "prix_actuel").state == "unknown"


async def test_tempo_inconnu_si_aucune_valeur_du_jour(hass, aioclient_mock, tempo_json, freezer):
    """Entité indisponible dès le départ, ni mémoire ni historique : inconnu, jamais un prix deviné."""
    await hass.config.async_set_time_zone("Europe/Paris")
    freezer.move_to("2026-11-23 11:00:00+00:00")
    aioclient_mock.get(URL, json=tempo_json)
    hass.states.async_set("sensor.couleur_tempo", "unavailable")
    entry = _entree(couleur_tempo="sensor.couleur_tempo")
    await _installer(hass, entry)
    assert _etat(hass, entry, "prix_actuel").state == "unknown"


async def test_tempo_relit_la_couleur_dans_l_historique(recorder_mock, hass, aioclient_mock, tempo_json, freezer):
    """Au démarrage, l'entité couleur est souvent indisponible : l'enregistreur donne la couleur du jour."""
    await hass.config.async_set_time_zone("Europe/Paris")
    aioclient_mock.get(URL, json=tempo_json)
    freezer.move_to("2026-11-23 07:00:00+00:00")  # 8h Paris : jour Tempo du 23
    hass.states.async_set("sensor.couleur_tempo", "Rouge")
    await async_wait_recording_done(hass)
    freezer.move_to("2026-11-23 11:00:00+00:00")  # 12h
    hass.states.async_set("sensor.couleur_tempo", "unavailable")
    await async_wait_recording_done(hass)

    entry = _entree(couleur_tempo="sensor.couleur_tempo")
    await _installer(hass, entry)
    p6 = tempo_json["actuelle"]["puissances"]["6"]["prix_ttc"]
    assert float(_etat(hass, entry, "prix_actuel").state) == p6["rouge_hp"]


async def test_ejp_0h_1h_relit_la_veille_dans_l_historique(recorder_mock, hass, aioclient_mock, ejp_json, freezer):
    """Installation ou redémarrage à 0h30, sans valeur retenue : la veille vient de l'historique."""
    await hass.config.async_set_time_zone("Europe/Paris")
    aioclient_mock.get("https://raphaelh.github.io/tarif-kwh/ejp.json", json=ejp_json)
    p = ejp_json["actuelle"]["puissances"]["12"]["prix_ttc"]
    freezer.move_to("2026-11-23 10:00:00+00:00")  # 11h Paris, le 23 : jour de pointe
    hass.states.async_set("binary_sensor.ejp_pointe", "on")
    await async_wait_recording_done(hass)
    freezer.move_to("2026-11-23 22:50:00+00:00")  # 23h50 : l'entité devient indisponible
    hass.states.async_set("binary_sensor.ejp_pointe", "unavailable")
    await async_wait_recording_done(hass)
    freezer.move_to("2026-11-23 23:30:00+00:00")  # 0h30 le 24 : nouveau jour normal
    hass.states.async_set("binary_sensor.ejp_pointe", "off")
    await async_wait_recording_done(hass)

    entry = _ejp_avec_entite()
    await _installer(hass, entry)
    assert float(_etat(hass, entry, "prix_actuel").state) == p["pointe"]


async def test_changer_la_puissance_garde_les_identifiants(hass, aioclient_mock, tempo_json):
    """La puissance se règle dans « Configurer » ; les entités gardent leur identifiant, sans kVA."""
    aioclient_mock.get(URL, json=tempo_json)
    entry = _entree()
    await _installer(hass, entry)
    reg = er.async_get(hass)
    ids = {e.entity_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)}
    assert ids and not any("kva" in i or "_6_" in i for i in ids)
    avant = _etat(hass, entry, "abonnement")
    assert avant.attributes["puissance_kva"] == "6"

    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"option": "tempo", "puissance": "18"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {})
    assert r["type"] == "create_entry"
    await hass.async_block_till_done()

    assert {e.entity_id for e in er.async_entries_for_config_entry(reg, entry.entry_id)} == ids
    apres = _etat(hass, entry, "abonnement")
    assert apres.entity_id == avant.entity_id
    assert apres.attributes["puissance_kva"] == "18"
    assert float(apres.state) == tempo_json["actuelle"]["puissances"]["18"]["abonnement_ttc"]


async def test_options_puissance_invalide_pour_l_option(hass, aioclient_mock, ejp_json):
    aioclient_mock.get("https://raphaelh.github.io/tarif-kwh/ejp.json", json=ejp_json)
    entry = MockConfigEntry(domain=DOMAIN, title="Tarif kWh", unique_id=DOMAIN, data={"option": "ejp", "puissance": "9"})
    await _installer(hass, entry)
    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"option": "ejp", "puissance": "6"})
    assert r["errors"] == {"puissance": "puissance_invalide"}


async def test_changer_d_option_garde_prix_actuel_et_retire_l_ancien(hass, aioclient_mock, tempo_json, hphc_json):
    """Tempo -> HP/HC : « Prix actuel » garde son identifiant, les capteurs Tempo disparaissent."""
    aioclient_mock.get(URL, json=tempo_json)
    aioclient_mock.get("https://raphaelh.github.io/tarif-kwh/hphc.json", json=hphc_json)
    entry = _entree(couleur_tempo="sensor.couleur_tempo")
    hass.states.async_set("sensor.couleur_tempo", "bleu")
    await _installer(hass, entry)
    reg = er.async_get(hass)
    prix_actuel_id = _etat(hass, entry, "prix_actuel").entity_id
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_prix_bleu_hc")

    r = await hass.config_entries.options.async_init(entry.entry_id)
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"option": "hphc", "puissance": "9"})
    r = await hass.config_entries.options.async_configure(r["flow_id"], {"heures_creuses": "22:00-06:00"})
    assert r["type"] == "create_entry"
    # La couleur Tempo, inutile en HP/HC, est effacée.
    assert r["data"]["couleur_tempo"] is None
    await hass.async_block_till_done()

    assert reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_prix_bleu_hc") is None
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_prix_hp")
    assert reg.async_get_entity_id("sensor", DOMAIN, f"{entry.entry_id}_prix_actuel") == prix_actuel_id
    assert hass.states.get(prix_actuel_id).attributes["periode"] in ("hp", "hc")


async def test_diagnostics(hass, aioclient_mock, tempo_json):
    from custom_components.tarif_kwh.diagnostics import async_get_config_entry_diagnostics

    aioclient_mock.get(URL, json=tempo_json, headers={"ETag": '"v1"'})
    entry = _entree(couleur_tempo="sensor.couleur_tempo")
    await _installer(hass, entry)
    diag = await async_get_config_entry_diagnostics(hass, entry)
    assert diag["reglages"]["couleur_tempo"] == "sensor.couleur_tempo"
    assert diag["lecture"] == {"url": URL, "derniere_reussie": True, "derniere_erreur": None, "etag": '"v1"'}
    assert diag["donnees"]["actuelle"]["date_effet"] == tempo_json["actuelle"]["date_effet"]
    assert "18" in diag["donnees"]["actuelle"]["puissances"]
    assert diag["donnees"]["prochaine"] is None
    assert diag["source"]["publication"] == "ok"
    assert diag["source"]["derniere_verification"]


def _issues(hass):
    from homeassistant.helpers import issue_registry as ir

    return {i for (d, i) in ir.async_get(hass).issues if d == DOMAIN}


async def test_pas_d_alerte_quand_la_source_est_a_jour(hass, aioclient_mock, tempo_json):
    aioclient_mock.get(URL, json=tempo_json)
    await _installer(hass, _entree())
    assert _issues(hass) == set()


async def test_alerte_source_plus_verifiee_puis_retablie(hass, aioclient_mock, tempo_json, etat_site, freezer):
    freezer.move_to("2026-11-24 10:00:00+00:00")
    aioclient_mock.get(URL, json=tempo_json, headers={"ETag": '"v1"'})
    entry = _entree()
    await _installer(hass, entry)
    coordinator = entry.runtime_data

    # La source ne répond plus : etat.json garde sa dernière date, qui vieillit.
    etat_site["exc"] = ClientError("coupé")
    freezer.move_to("2026-11-30 10:00:00+00:00")  # 6 jours : pas encore d'alerte
    await coordinator.async_refresh()
    assert _issues(hass) == set()
    freezer.move_to("2026-12-02 10:00:00+00:00")  # 8 jours
    await coordinator.async_refresh()
    assert _issues(hass) == {"donnees_anciennes"}
    assert coordinator.data == tempo_json  # les prix restent ceux de la dernière lecture

    # Source de nouveau vérifiée : l'alerte disparaît.
    del etat_site["exc"]
    await coordinator.async_refresh()
    assert _issues(hass) == set()


async def test_alerte_source_ancienne_retrouvee_apres_redemarrage(hass, aioclient_mock, tempo_json, etat_site, freezer):
    """La date de dernière vérification est gardée dans le Store : hors ligne au démarrage, l'alerte reste juste."""
    freezer.move_to("2026-11-24 10:00:00+00:00")
    aioclient_mock.get(URL, json=tempo_json)
    entry = _entree()
    await _installer(hass, entry)
    assert await hass.config_entries.async_unload(entry.entry_id)

    aioclient_mock.clear_requests()
    aioclient_mock.get(URL, exc=ClientError("coupé"))
    etat_site["exc"] = ClientError("coupé")
    freezer.move_to("2026-12-05 10:00:00+00:00")
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    assert _issues(hass) == {"donnees_anciennes"}


async def test_alerte_publication_bloquee(hass, aioclient_mock, tempo_json, etat_site):
    etat_site["options"] = {"tempo": {"publication": "bloquee"}, "base": {"publication": "ok"}}
    aioclient_mock.get(URL, json=tempo_json)
    entry = _entree()
    await _installer(hass, entry)
    assert _issues(hass) == {"publication_bloquee"}

    etat_site["options"]["tempo"]["publication"] = "ok"
    await entry.runtime_data.async_refresh()
    assert _issues(hass) == set()
