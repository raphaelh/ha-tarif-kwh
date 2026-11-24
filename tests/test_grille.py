import copy
from datetime import date, time


def test_valider(grille_mod, tempo_json):
    assert grille_mod.valider(tempo_json, "tempo") is None
    assert "option" in grille_mod.valider(tempo_json, "base")
    assert grille_mod.valider([], "tempo")
    mauvais = {**tempo_json, "schema_version": 2}
    assert "schema_version" in grille_mod.valider(mauvais, "tempo")
    sans = {k: v for k, v in tempo_json.items() if k != "actuelle"}
    assert grille_mod.valider(sans, "tempo")


def test_prix_courants(grille_mod, tempo_json):
    g = grille_mod.grille_en_vigueur(tempo_json, date(2026, 11, 23))
    assert g["date_effet"] == tempo_json["actuelle"]["date_effet"]
    assert grille_mod.prix_ttc(g, "6", "bleu_hc") == tempo_json["actuelle"]["puissances"]["6"]["prix_ttc"]["bleu_hc"]
    assert grille_mod.abonnement_ttc(g, "6") == tempo_json["actuelle"]["puissances"]["6"]["abonnement_ttc"]
    assert grille_mod.prix_ttc(g, "3", "bleu_hc") is None  # pas de 3 kVA en Tempo
    assert grille_mod.prix_ttc(g, "6", "inconnue") is None
    assert grille_mod.prix_ttc(None, "6", "bleu_hc") is None


def _avec_prochaine(tempo_json, date_effet="2027-02-01", delta=0.01):
    d = copy.deepcopy(tempo_json)
    p = copy.deepcopy(d["actuelle"])
    p["date_effet"] = date_effet
    for pu in p["puissances"].values():
        pu["prix_ttc"] = {k: round(v + delta, 4) for k, v in pu["prix_ttc"].items()}
    d["prochaine"] = p
    return d


def test_prochaine_grille_appliquee_a_sa_date_sans_nouvelle_lecture(grille_mod, tempo_json):
    d = _avec_prochaine(tempo_json)
    avant = grille_mod.grille_en_vigueur(d, date(2027, 1, 31))
    jour_j = grille_mod.grille_en_vigueur(d, date(2027, 2, 1))
    apres = grille_mod.grille_en_vigueur(d, date(2027, 6, 1))
    assert avant["date_effet"] == d["actuelle"]["date_effet"]
    assert jour_j["date_effet"] == "2027-02-01"
    assert apres["date_effet"] == "2027-02-01"
    assert grille_mod.prix_ttc(jour_j, "6", "bleu_hc") == round(
        grille_mod.prix_ttc(avant, "6", "bleu_hc") + 0.01, 4
    )


def test_date_effet_illisible_ignoree(grille_mod, tempo_json):
    d = _avec_prochaine(tempo_json, date_effet="n'importe quoi")
    assert grille_mod.grille_en_vigueur(d, date(2030, 1, 1)) == d["actuelle"]


def test_parse_plages(grille_mod):
    assert grille_mod.parse_plages("22:00-06:00") == [(time(22), time(6))]
    assert grille_mod.parse_plages("13:00-15:00, 01:30-07:30") == [
        (time(13), time(15)),
        (time(1, 30), time(7, 30)),
    ]
    assert grille_mod.parse_plages("") == []
    for mauvais in ("22h-6h", "22:00", "25:00-06:00"):
        try:
            grille_mod.parse_plages(mauvais)
        except ValueError:
            continue
        raise AssertionError(mauvais)


def test_dans_plages_minuit(grille_mod):
    nuit = grille_mod.parse_plages("22:00-06:00")
    assert grille_mod.dans_plages(time(22, 0), nuit)
    assert grille_mod.dans_plages(time(23, 59), nuit)
    assert grille_mod.dans_plages(time(0, 0), nuit)
    assert grille_mod.dans_plages(time(5, 59), nuit)
    assert not grille_mod.dans_plages(time(6, 0), nuit)
    assert not grille_mod.dans_plages(time(21, 59), nuit)


def test_normaliser_couleur(grille_mod):
    assert grille_mod.normaliser_couleur("Bleu") == "bleu"
    assert grille_mod.normaliser_couleur("blue") == "bleu"
    assert grille_mod.normaliser_couleur("WHITE") == "blanc"
    assert grille_mod.normaliser_couleur("Jour Rouge") == "rouge"
    for inconnu in ("unknown", "unavailable", "", None):
        assert grille_mod.normaliser_couleur(inconnu) is None


def test_periode_courante(grille_mod):
    tempo_hc = grille_mod.parse_plages("22:00-06:00")
    f = grille_mod.periode_courante
    assert f("base", time(12)) == "base"
    assert f("tempo", time(7), couleur="rouge", plages_tempo_hc=tempo_hc) == "rouge_hp"
    assert f("tempo", time(23), couleur="blanc", plages_tempo_hc=tempo_hc) == "blanc_hc"
    assert f("tempo", time(23), couleur=None, plages_tempo_hc=tempo_hc) is None
    hc = grille_mod.parse_plages("01:30-07:30,12:30-14:30")
    assert f("hphc", time(13), plages_hc=hc) == "hc"
    assert f("hphc", time(8), plages_hc=hc) == "hp"
    assert f("hphc", time(8), plages_hc=[]) is None
    assert f("ejp", time(8)) == "normal"
    assert f("inconnue", time(8)) is None


def test_normaliser_pointe(grille_mod):
    for vrai in ("on", "True", "pointe", "oui"):
        assert grille_mod.normaliser_pointe(vrai) is True
    for faux in ("off", "normal", "false"):
        assert grille_mod.normaliser_pointe(faux) is False
    for inconnu in ("unknown", "unavailable", "", None):
        assert grille_mod.normaliser_pointe(inconnu) is None


def test_periode_courante_ejp(grille_mod):
    pointe = grille_mod.parse_plages("07:00-01:00")
    f = grille_mod.periode_courante
    assert f("ejp", time(12), jour_pointe=True, plages_pointe=pointe) == "pointe"
    assert f("ejp", time(23, 30), jour_pointe=True, plages_pointe=pointe) == "pointe"
    assert f("ejp", time(0, 30), jour_pointe=True, plages_pointe=pointe) == "pointe"
    assert f("ejp", time(3), jour_pointe=True, plages_pointe=pointe) == "normal"
    assert f("ejp", time(12), jour_pointe=False, plages_pointe=pointe) == "normal"
    assert f("ejp", time(12), plages_pointe=pointe) == "normal"  # sans entité
    assert f("ejp", time(12), jour_pointe=None, plages_pointe=pointe) is None  # entité inconnue
