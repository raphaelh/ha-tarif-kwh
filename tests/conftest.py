"""Fixtures communes ; les tests purs chargent grille.py sans importer Home Assistant."""

import importlib.util
import json
import pathlib

import pytest

RACINE = pathlib.Path(__file__).parent
GRILLE_PY = RACINE.parent / "custom_components" / "tarif_kwh" / "grille.py"


@pytest.fixture(scope="session")
def grille_mod():
    spec = importlib.util.spec_from_file_location("grille_isolee", GRILLE_PY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def tempo_json():
    return json.loads((RACINE / "data" / "tempo.json").read_text())


@pytest.fixture
def ejp_json():
    return json.loads((RACINE / "data" / "ejp.json").read_text())


@pytest.fixture
def hphc_json():
    return json.loads((RACINE / "data" / "hphc.json").read_text())
