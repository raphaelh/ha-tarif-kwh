# Tarif kWh pour Home Assistant

Intégration Home Assistant (installable par [HACS](https://hacs.xyz)) qui expose le **prix TTC du kWh du Tarif Bleu EDF**
(Base, Heures pleines/creuses, Tempo, EJP) sous forme de capteurs. Les prix viennent du projet
[raphaelh/tarif-kwh](https://github.com/raphaelh/tarif-kwh), publiés sur <https://raphaelh.github.io/tarif-kwh/>.

> **Projet non officiel**, sans lien avec EDF, la CRE ou les pouvoirs publics. Les prix sont issus de publications
> officielles, sans garantie : vérifiez sur votre facture.

## Installation

1. HACS → ⋮ → **Dépôts personnalisés** → `https://github.com/raphaelh/ha-tarif-kwh`, catégorie **Intégration**.
2. Installer **Tarif kWh**, redémarrer Home Assistant.
3. Paramètres → Appareils et services → **Ajouter une intégration** → *Tarif kWh*.

## Configuration

On choisit l'**option** (Base, HP/HC, Tempo, EJP) et la **puissance** (kVA). On peut ajouter l'intégration plusieurs fois
(une par option/puissance). Deux réglages facultatifs, modifiables ensuite par **Configurer** :

| Réglage | Sert à |
|---|---|
| Entité de la couleur Tempo | Calculer le capteur *Prix actuel* en Tempo. Les états `bleu`/`blanc`/`rouge` (ou `blue`/`white`/`red`) sont reconnus ; l'entité doit donner la couleur du **jour Tempo en cours** (qui change à 6 h). |
| Entité « jour de pointe EJP » | Suivre les 22 jours de pointe en EJP. États `on`/`off` ou `pointe`/`normal` ; le prix « pointe » s'applique de 7 h à 1 h les jours de pointe. À 1 h près : l'entité est lue comme un indicateur du jour calendaire, et la tranche 0 h-1 h suivant un jour de pointe reste au prix normal. Sans entité, le prix « normal » est utilisé tout le temps (attribut `jours_de_pointe_suivis: false`). |
| Heures creuses | Calculer le capteur *Prix actuel* en HP/HC, ex. `22:00-06:00` ou `01:30-07:30,12:30-14:30`. Elles sont propres à votre compteur (Enedis) et ne sont pas publiées. |

## Capteurs

Pour chaque entrée :

- **Prix `<période>`** : un capteur par période de l'option (`EUR/kWh`, TTC) : Base ; HP, HC ; bleu/blanc/rouge × HC/HP ;
  normal, pointe.
- **Abonnement** : TTC en `EUR/an` (attribut `abonnement_ttc_mensuel`).
- **Date d'effet de la grille** (désactivé par défaut) : avec le statut de la grille et `ttc_estime`.
- **Prix actuel** (Base ; EJP ; Tempo avec une entité couleur ; HP/HC avec des heures creuses) : le prix du kWh à cet instant,
  utilisable comme « entité de prix » dans le tableau de bord **Énergie**.

## Fonctionnement

- Une **lecture par jour** de `https://raphaelh.github.io/tarif-kwh/<option>.json`, avec `If-None-Match` : tant que rien ne
  change, GitHub Pages répond 304 sans corps. Les tarifs ne changent que quelques fois par an.
- Le fichier contient la grille **actuelle** et, dès que la CRE la propose, la **prochaine** avec sa date d'effet.
  L'intégration choisit la grille **d'après la date d'effet, en local** : le changement du 1er août ou du 1er février
  s'applique à minuit pile, sans attendre une nouvelle lecture.
- La dernière version valable est conservée (stockage de Home Assistant) : en cas de panne réseau, y compris au démarrage,
  les prix restent ceux de la dernière lecture.
- Les prix TTC marqués `ttc_estime` dans les données sont calculés par le projet source (voir son README).

## Développement

```bash
pip install -r requirements_test.txt
pytest
```

`custom_components/tarif_kwh/grille.py` contient la logique sans dépendance à Home Assistant.

Licence MIT.
