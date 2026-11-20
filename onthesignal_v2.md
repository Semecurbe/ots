# Onthesignal — Cahier des charges v2

| Version | Date | Objet |
| --- | --- | --- |
| v1 | 2026-11 | Expression initiale du besoin (`onthesignal.md`) |
| v2 | 2026-11-17 | Version corrigée, structurée et précisée en vue du développement |
| v2.1 | 2026-11-17 | Intégration des décisions sur les points ouverts (§22) |
| v2.2 | 2026-11-20 | Phase 2 : renvoi vers son cahier des charges, [`onthesignal_web.md`](onthesignal_web.md), et NiceGUI 4 (§1, §4.1, §21.2) |

## Lecture du document

- **P1** : indispensable à la première version utilisable · **P2** : important · **P3** : confort ou évolution. Priorités validées le 2026-11-17.
- Les choix techniques non tranchés dans la v1 ont été proposés lors de la reprise du document, puis validés le 2026-11-17 : ils sont récapitulés au §22.
- Les noms de fonctions, de paramètres, de commandes et de fichiers en `police fixe` sont les noms cibles de l'implémentation. Le logiciel est entièrement en anglais (§3.2) ; seul le présent document est rédigé en français.

## Sommaire

1. Objet et contexte
2. Périmètre et phasage
3. Glossaire et conventions
4. Architecture et règles de conception
5. Modèle de données
6. Lecture et export de fichiers
7. Prétraitements communs
8. Analyse de bruit
9. Comparaison au modèle de bruit de Peterson
10. Analyses sur sinus (SINAD, ENOB, SFDR, THD, analyse dynamique)
11. Mesures temporelles
12. Cohérence et spectrogramme
13. Acquisition et temps réel SeedLink
14. Rapports
15. Interface terminal (IHM)
16. Scripts standardisés et traitements par lots
17. Assistant IA
18. **Documentation — livrable obligatoire**
19. Qualité, tests et validation
20. Exigences non fonctionnelles
21. Organisation du code et lots de développement
22. Décisions sur les points ouverts

- Annexe A — Références
- Annexe B — Corrections apportées à la v1

---

## 1. Objet et contexte

Onthesignal est un logiciel de traitement du signal dédié à la **caractérisation des chaînes d'acquisition sismiques** : bruit propre d'un numériseur, dynamique, performances sur sinus (SINAD, ENOB, SFDR, THD), comparaison au modèle de bruit sismique de Peterson, mesures temporelles et spectrales.

Les analyses portent principalement sur des **enregistrements** (fichiers miniSEED). Une analyse limitée est également possible sur des **flux temps réel** SeedLink.

Utilisateurs visés : ingénieurs et techniciens en instrumentation sismique, à l'aise avec Python et le terminal Linux.

Le projet comporte deux phases :

1. **Phase 1 — objet du présent document** : application en ligne de commande, sous forme de console interactive dans un terminal Linux.
2. **Phase 2** : interface web (NiceGUI 4 + µPlot), objet d'un cahier des charges distinct, [`onthesignal_web.md`](onthesignal_web.md). La phase 1 doit dès maintenant respecter les règles d'architecture du §4, afin que le cœur de calcul soit réutilisé sans modification par l'interface web.

Le logiciel est livré avec une **documentation complète des algorithmes et du fonctionnement** (§18). Cette documentation est un livrable à part entière, au même titre que le code.

## 2. Périmètre et phasage

### 2.1 Fonctionnalités de la phase 1

| Domaine | Contenu | Priorité | Section |
| --- | --- | --- | --- |
| Données | Objet `Signal`, session, lecture miniSEED et texte, export | P1 | 5, 6 |
| Bruit | `noise`, `noise_fft`, `noise_dsp`, dynamique (DR) | P1 | 8 |
| Modèle de Peterson | `lnm` (NLNM / NHNM) | P1 | 9 |
| Sinus | ajustement 4 paramètres, `sinad` / ENOB, `sfdr`, `thd`, `dynamic` | P1 | 10 |
| Rapports | génération `.qmd` (Quarto) + figures → PDF ou HTML | P1 | 14 |
| Acquisition | refonte de `acq_mseed.py`, progression en temps réel | P1 | 13.1 |
| IHM | console, commandes `/`, formulaires de paramètres, édition de scripts | P1 | 15 |
| Scripts | modèle de script standardisé, exécution, traitements par lots | P1 | 16 |
| Documentation | algorithmes, manuel utilisateur, documentation développeur (Quarto, en anglais) | **P1 — obligatoire** | 18 |
| Mesures | `frequency`, `period`, `delay50` | P2 | 11 |
| Spectral | `coherence`, `spectrogram` | P2 | 12 |
| Temps réel | moyenne, écart-type, C-C, FFT, DSP de Welch sur flux SeedLink | P2 | 13.2 |
| IA | Claude, ChatGPT, Ollama ; fichier `agent.md` ; `/init` ; contexte ; génération de scripts | P2 | 17 |

### 2.2 Hors périmètre de la phase 1

- Interface web (phase 2).
- Correction de la réponse instrumentale complète (pôles et zéros) : la conversion en unités physiques utilise une **sensibilité scalaire**, supposée plate dans la bande d'étude.
- Analyses temps réel autres que celles du §13.2.

### 2.3 Évolutions envisagées (pour mémoire)

- Bruit propre par corrélation à 2 voies (Holcomb, 1989) ou à 3 voies (Sleeman et al., 2006), en s'appuyant sur `coherence`.
- DSP probabilistes sur de longues durées (PPSD, McNamara & Buland, 2004).
- Lecture des réponses instrumentales StationXML complètes.

## 3. Glossaire et conventions

### 3.1 Glossaire

| Terme | Définition |
| --- | --- |
| count, LSB | Unité brute du numériseur (un pas de quantification). |
| NSLC | Identifiant SEED `Réseau.Station.Location.Voie`, par ex. `RD.SN270.00.FHZ`. |
| Sensibilité | Coefficient de conversion des counts en unité physique, exprimé en unité physique par count : valeur physique = counts × sensibilité (§3.2). |
| PE | Pleine échelle du numériseur, **crête-à-crête**, exprimée dans l'unité brute des données (counts) ; 2^24 par défaut (24 bits). |
| RMS | Valeur efficace. Pour un bruit, elle est calculée après retrait de la moyenne (= écart-type). |
| C-C | Valeur crête-à-crête (max − min). |
| DSP | Densité spectrale de puissance unilatérale (unité²/Hz). ASD : sa racine carrée (unité/√Hz). |
| Welch | Estimation de la DSP par moyenne de périodogrammes de segments fenêtrés et recouvrants. |
| ENBW | Bande équivalente de bruit d'une fenêtre ou d'un filtre. |
| NLNM / NHNM | Modèles de bruit sismique minimal / maximal de Peterson (1993). |
| DR | Dynamique (*dynamic range*) : rapport entre le RMS d'un sinus pleine échelle et le bruit RMS (§8.1). |
| SINAD | Rapport signal sur bruit et distorsion. |
| ENOB | Nombre de bits effectifs (*Effective Number Of Bits*). |
| SNR | Rapport signal sur bruit, harmoniques exclues. |
| THD | Distorsion harmonique totale. |
| SFDR | Dynamique sans raie parasite (*Spurious-Free Dynamic Range*). |
| Analyse dynamique | Ensemble SINAD, ENOB, SNR, THD et SFDR mesuré sur un sinus (§10.5) — à ne pas confondre avec la dynamique DR. |
| Ajustement 4 paramètres | Ajustement par moindres carrés d'un sinus (amplitude, phase, offset, fréquence) selon IEEE Std 1057. |
| Secteur | Raie du réseau électrique à 50 Hz (60 Hz paramétrable) et ses harmoniques. |
| miniSEED | Format d'échange des séries temporelles sismiques. |
| SeedLink | Protocole de diffusion temps réel de données sismiques. |

### 3.2 Conventions

- **Temps** : UTC (`obspy.UTCDateTime`) ; durées en secondes ; fréquences en Hz.
- **Sensibilité** : coefficient multiplicatif, en unité physique par count : `physical = counts * sensitivity` (ex. 40 V crête-à-crête / 2^24 counts ≈ 2,384·10⁻⁶ V/count). Les fichiers StationXML expriment la sensibilité en counts par unité physique : lors de leur intégration (§6.1, P3), la valeur lue sera inversée.
- **Unités physiques reconnues** : `counts`, `V`, `m`, `m/s`, `m/s**2`. Les variantes courantes (`m/s2`, `m/s²`, `m.s-2`…) sont normalisées à la lecture.
- **Amplitude** d'un sinus : amplitude crête, sauf mention « RMS ».
- **DSP** : unilatérale, en unité²/Hz ; en décibels : `10·log10(DSP)`, en dB réf. 1 unité²/Hz.
- **dBFS** : relatif au sinus pleine échelle (crête PE/2, RMS PE/(2√2)) ; un sinus pleine échelle vaut 0 dBFS.
- **dBc** : relatif à l'amplitude de la fondamentale.
- **Délai** : `Δt = t(S2) − t(S1)`, positif lorsque S2 est en retard sur S1.
- **Noms des fonctions** : en minuscules (PEP 8) — `sinad`, `sfdr`, `thd` — avec des alias en majuscules (`SINAD`, `SFDR`, `THD`) disponibles dans la console.
- **Langue** : tout le logiciel est en anglais, sans texte en français : code (identifiants, commentaires, docstrings), interface (commandes, messages, aide, formulaires), documentation, fichier `agent.md` destiné à l'IA et rapports générés. Seul le présent cahier des charges est rédigé en français ; les exemples de sortie console qu'il contient sont donnés en anglais.

## 4. Architecture et règles de conception

### 4.1 Technologies

| Usage | Choix | Statut |
| --- | --- | --- |
| Langage | Python ≥ 3.11 | Imposé |
| Calcul numérique | numpy, scipy | Imposé |
| Données sismiques, SeedLink, modèles de Peterson | ObsPy | Imposé |
| Graphiques (phase 1) | matplotlib | Imposé |
| Saisie console, complétion `/`, historique | prompt_toolkit | Recommandé |
| Tableaux, couleurs, barres de progression | rich | Recommandé |
| Modèles de rapports et de scripts | Jinja2 | Recommandé |
| Rapports | Quarto (outil externe), format `.qmd` | Imposé |
| Documentation | Quarto (site web, export PDF possible) + quartodoc (référence de l'API) | Imposé |
| IA | SDK `anthropic`, `openai`, `ollama` (dépendances optionnelles) | Recommandé |
| Web (phase 2) | NiceGUI 4 + µPlot (versions : `onthesignal_web.md` §3.1) | Imposé pour la phase 2 |

### 4.2 Couches logicielles

Chaque couche ne dépend que des couches situées en dessous d'elle :

```text
Interfaces   cli (phase 1)                web NiceGUI + µPlot (phase 2)
Services     session · registre des commandes · rapports · IA · scripts
Rendu        plot : figures matplotlib construites à partir des Result
Cœur         core (Signal, Result, Param) · io · processing · analysis · seedlink
```

### 4.3 Règles de conception (obligatoires)

- **R1 — Séparation calcul / affichage / interface.** Les paquets `core`, `io`, `processing` et `analysis` n'importent ni matplotlib, ni prompt_toolkit, ni rich, et n'écrivent rien sur la sortie standard (journalisation via `logging`).
- **R2 — Analyses pures.** Une analyse est une fonction `analyse(signal(s), **params) -> Result`, sans état global et sans modification des signaux d'entrée.
- **R3 — Paramètres déclarés une seule fois.** Chaque analyse déclare ses paramètres (`Param` : nom, type, défaut, unité, bornes, description). Cette déclaration unique alimente la signature Python, les formulaires de la console, l'aide `/help`, le schéma d'outil transmis à l'IA (JSON Schema) et, en phase 2, les formulaires web.
- **R4 — Résultats sérialisables.** Tout `Result` est convertible en dictionnaire / JSON (`to_dict()`), pour le rendu matplotlib (phase 1), le rendu µPlot (phase 2), les rapports et l'IA.
- **R5 — Rendu séparé.** Les fonctions `plot_*` reçoivent un `Result` et renvoient une `matplotlib.figure.Figure` ; elles ne recalculent rien et n'appellent jamais `plt.show()` de façon bloquante. L'interface décide d'afficher ou d'enregistrer la figure.
- **R6 — État dans une `Session`.** Signaux, résultats, configuration et historique sont portés par un objet `Session`, sans variable globale (en phase 2 : une session par utilisateur).
- **R7 — Opérations longues non bloquantes.** Acquisition, temps réel et traitement de gros fichiers s'exécutent dans un thread ou une tâche asyncio, publient leur avancement par rappel (`on_progress(fraction, message)`) et sont interruptibles.
- **R8 — Registre unique des commandes.** Chaque fonctionnalité exposée (commande `/`, outil IA, futur élément web) est enregistrée une seule fois (nom, description, paramètres, fonction). La console, l'aide et l'IA sont construites à partir de ce registre.
- **R9 — Traçabilité.** Chaque `Result` contient les paramètres effectivement utilisés, l'identité des signaux (NSLC, source, empreinte SHA-256 du fichier), la version du logiciel et l'horodatage.

### 4.4 Contraintes anticipées pour la phase 2

- NiceGUI repose sur asyncio : aucun appel bloquant dans les services (R7).
- µPlot trace des courbes x/y (échelles logarithmiques possibles) : les `Result` exposent leurs courbes sous forme de tableaux (`x`, `y`) directement transposables. Le spectrogramme (carte de couleurs) nécessitera un rendu image ou un autre composant.
- Les longues séries temporelles sont décimées pour l'affichage (enveloppe min/max par pixel) ; cette fonction de décimation est commune aux deux interfaces.

## 5. Modèle de données

### 5.1 Objet `Signal` — P1

| Attribut | Type | Description |
| --- | --- | --- |
| `name` | str | Nom dans la session (`S1`, `S2`… par défaut, ou nom choisi) |
| `title` | str | Titre lisible affiché dans les titres de figures, `list_sig()` et les rapports ; par défaut le nom du fichier sans extension, modifiable (`S1.title = "..."`, option `title=` de `load`) |
| `network`, `station`, `location`, `channel` | str | Codes NSLC |
| `id` | str, lecture seule | `NET.STA.LOC.CHA` |
| `data` | `numpy.ndarray` (float64) | Échantillons bruts (counts) ; le type d'origine est conservé dans `metadata` |
| `sampling_rate` | float | Fréquence d'échantillonnage (Hz) |
| `starttime` | UTCDateTime | Instant du premier échantillon |
| `delta`, `npts`, `endtime`, `duration`, `nyquist` | lecture seule | Valeurs dérivées |
| `unit` | str | Unité physique (§3.2) ; `counts` par défaut |
| `sensitivity` | float | Unité physique par count (coefficient multiplicatif) ; 1.0 par défaut |
| `full_scale` | float | PE crête-à-crête dans l'unité brute ; `2**24` par défaut |
| `source` | str | Fichier ou flux d'origine, avec empreinte SHA-256 |
| `gaps` | list | Trous détectés au chargement et traitement appliqué |
| `metadata` | dict | Informations libres : numériseur, gain, n° de série, capteur, commentaire… |
| `history` | list[str] | Traitements successifs (traçabilité) |

#### Création

- `Signal(data, sampling_rate, starttime=None, network="XX", station="", location="", channel="", unit="counts", sensitivity=1.0, full_scale=2**24, metadata=None)`
- `Signal.from_trace(trace)` et `S.to_trace()` pour l'interopérabilité avec ObsPy.
- `load(...)` pour les fichiers (§6).
- `make_sine(frequency, ratio, bits, ...)` et `make_noise(rms, color, bits, ...)` : signaux de test d'un numériseur idéal N bits (pleine échelle `2**bits`, quantification, saturation), amplitude du sinus en fraction de la pleine échelle (`ratio`) ou en dBFS, bruit ajouté, harmoniques, raie secteur, graine aléatoire enregistrée ; commandes `/make_sine` et `/make_noise`.

#### Méthodes

| Méthode | Rôle | Priorité |
| --- | --- | --- |
| `S.print()` (et `str(S)`) | Affiche tous les attributs et les statistiques de base (moyenne, écart-type, C-C, min, max) | P1 |
| `S.show(units="physical", t_start=None, t_end=None)` | Tracé temporel matplotlib : titre NSLC, axes avec unités, temps UTC | P1 |
| `S.copy()`, `S.slice(t_start, t_end)` | Copie ; extraction d'une fenêtre temporelle | P1 |
| `S.to_physical()` | Données en unités physiques (`data * sensitivity`) | P1 |
| `S.to_dict()` | Sérialisation (métadonnées et statistiques, sans les échantillons par défaut) | P1 |
| `S.noise()`, `S.lnm()`, `S.sinad()`… | Raccourcis : `S.lnm(**p)` équivaut à `lnm(S, **p)` | P1 |
| `S.detrend()`, `S.filter()`, `S.resample()` | Prétraitements renvoyant un nouveau signal | P2 |
| `S.save(path)` | Export (§6.3) | P2 |

Exemple de sortie de `S.print()` :

```text
>>> S1.print()
Signal S1 — RD.SN270.00.FHZ
  Title              acquisition_FHZ
  Source             acquisition_FHZ.mseed (sha256 3f2a…9c1e)
  Start → end (UTC)  2026-11-17T10:00:00.000 → 2026-11-17T10:10:00.000
  Duration           600.000 s · 600000 samples
  Sampling rate      1000.0 Hz (Nyquist 500.0 Hz)
  Unit               V
  Sensitivity        2.384e-06 V/count
  Full scale         16777216 counts p-p (2**24)
  Statistics         mean 12.3 · std 2.28 · p-p 22 · min 1 · max 23 (counts)
  Gaps               none
  History            loaded from acquisition_FHZ.mseed
```

#### Opérateurs — P1

Les opérations renvoient toujours un **nouveau** signal (l'original n'est jamais modifié) et complètent `history`.

| Opération | Effet |
| --- | --- |
| `k * S`, `S * k`, `S / k`, `-S` | Amplitude multipliée ou divisée par le scalaire `k` (`2 * S` double l'amplitude) |
| `S1 + S2`, `S1 - S2` | Somme ou différence échantillon par échantillon sur la fenêtre temporelle commune |

Règles applicables à `S1 ± S2` :

1. Les unités doivent être identiques ; sinon, erreur explicite.
2. Les temps sont « cohérents » si les deux signaux se recouvrent temporellement ; sinon, erreur. Le résultat couvre l'intersection des deux fenêtres.
3. Même fréquence d'échantillonnage et grilles alignées (décalage inférieur à 1 % de `delta`) : opération directe.
4. Sinon, `S2` est interpolé sur la grille temporelle de `S1` (interpolation linéaire par défaut ; `cubic` ou `lanczos` via `S1.add(S2, method=...)`). Si les fréquences d'échantillonnage diffèrent, `S2` est d'abord rééchantillonné à celle de `S1` avec filtre anti-repliement. Toute interpolation est signalée par un avertissement.
5. Si les sensibilités diffèrent, `S2` est ramené dans les counts de `S1` (`data2 × sens2 / sens1`) ; le résultat hérite de la sensibilité et des codes NSLC de `S1`.

### 5.2 Objet `Result` — P1

Toute analyse renvoie un `Result` (ou une classe dérivée) :

| Champ | Contenu |
| --- | --- |
| `kind` | Type d'analyse (`noise`, `lnm`, `sinad`…) |
| `signals` | Identité des signaux analysés (nom, NSLC, source, empreinte) |
| `params` | Paramètres effectivement utilisés, après application des défauts et des ajustements (ex. `fmax` ramené à Nyquist) |
| `values` | Grandeurs scalaires avec unité et libellé (ex. RMS en counts et en V, DR en dB) |
| `curves` | Courbes pour le rendu : `x`, `y`, libellés, unités, échelles |
| `warnings` | Avertissements : saturation, trous, bande réduite, nombre de périodes insuffisant… |
| `meta` | Version du logiciel, date, durée de calcul |

Méthodes : `print()` (tableau), `plot()` (renvoie une figure), `show()`, `to_dict()` / `to_json()`, `save(path)` (JSON ou CSV).

**Convention d'appel.** `noise(S)` calcule, affiche selon le contexte et **renvoie** le `Result`, exploitable dans un script : `r = noise(S, show=False); r.values["rms"]`. Paramètres communs à toutes les analyses :

- `show` : `None` (défaut) = affichage en console interactive, pas d'affichage dans un script ou un lot ; `True` / `False` pour forcer ;
- `save` : chemin d'enregistrement de la figure (`.png`, `.svg`, `.pdf`).

### 5.3 Session — P1

- La session contient les signaux, les résultats, la configuration et l'historique des commandes.
- Tout `Signal` affecté à une variable de la console est enregistré dans la session sous ce nom (`S3 = S1 + S2` crée `S3`). `load()` crée `S1`, `S2`… ou les noms demandés.
- `list_sig()` affiche le tableau des signaux :

```text
>>> list_sig()
 Name  NSLC             fs (Hz)  Start (UTC)              Duration  N       Unit  Sensitivity   Source
 S1    RD.SN270.00.FHZ  1000.0   2026-11-17T10:00:00.000  00:10:00  600000  V     2.384e-6 V/c  acquisition_FHZ.mseed
 S2    RD.SN270.00.FHN  1000.0   2026-11-17T10:00:00.000  00:10:00  600000  V     2.384e-6 V/c  acquisition_FHZ.mseed
```

- `rename_sig(old, new)`, `rm_sig(name)`, `list_res()` (résultats de la session) — P2.
- Sauvegarde et restauration de session — P3.

## 6. Lecture et export de fichiers

### 6.1 miniSEED — P1

`load(path, select=None, starttime=None, endtime=None, gaps="longest", sensitivity=None, unit=None, full_scale=None, name=None)`

- Lecture par ObsPy (miniSEED 2 ; miniSEED 3 si ObsPy le permet — P3).
- Un `Signal` par voie NSLC ; `select` filtre les voies par motif (`*.*.*.HH?`) ; `starttime` / `endtime` limitent la lecture.
- Les enregistrements d'une même voie sont fusionnés. Politique des trous `gaps` :
  - `longest` (défaut) : conservation du plus long segment continu ;
  - `fill` : comblement par interpolation linéaire ;
  - `split` : un signal par segment continu ;
  - `error` : refus du fichier.
- Quelle que soit la politique, les trous (début, durée) sont enregistrés dans `S.gaps`, affichés par `S.print()` et rappelés dans les résultats : **aucun comblement silencieux**.
- Sensibilité, unité, PE et métadonnées peuvent être fournies au chargement ou modifiées ensuite (`S1.sensitivity = 2.384e-6; S1.unit = "V"`).
- Lecture de la sensibilité et de l'unité depuis un fichier StationXML, la sensibilité lue (counts par unité) étant inversée (§3.2) — P3.
- Autres formats lus par ObsPy (SAC, GSE2…) — P3.

### 6.2 Fichiers texte multicolonnes — P1

`load(path, fmt="txt", n_channels=..., time_col=None, fs=None, ...)`

| Paramètre | Défaut | Description |
| --- | --- | --- |
| `n_channels` | demandé à l'utilisateur | Nombre de voies (colonnes de données) |
| `time_col` | `None` | Indice de la colonne de temps ; `None` = pas de colonne de temps |
| `fs` | `None` | Fréquence d'échantillonnage ; **obligatoire** en l'absence de colonne de temps |
| `delimiter` | détection automatique | Espace, tabulation, `;` ou `,` |
| `decimal` | `"."` | Séparateur décimal (`","` accepté) |
| `skiprows`, `comment` | détection automatique, `"#"` | Lignes d'en-tête et de commentaire ignorées |
| `time_format` | `"relative"` | `"relative"` (secondes), `"epoch"` ou `"iso"` |
| `starttime` | 1970-01-01T00:00:00 | Origine des temps si la colonne de temps est relative ou absente |
| `names`, `units`, `sensitivities` | voir description | Codes et paramètres par voie ; noms par défaut `XX.<file>..C01`, `C02`… |

Règles :

- Le nombre de colonnes détecté doit être égal à `n_channels` (+ 1 si `time_col` est renseigné) ; sinon, erreur indiquant le nombre de colonnes trouvées.
- Avec colonne de temps : `fs = 1 / médiane(diff(t))`. Si l'écart maximal au pas médian dépasse 1 % (configurable), erreur ; un rééchantillonnage peut être demandé explicitement.
- En console, `/load fichier.txt` ouvre un formulaire qui demande au minimum le nombre de voies, la présence et la position de la colonne de temps et, si nécessaire, la fréquence d'échantillonnage.

### 6.3 Export — P2

- `S.save("x.mseed")` : miniSEED, encodage STEIM2 pour des counts entiers, flottants sinon ; vérification de la longueur des codes NSLC (contraintes SEED) avec avertissement.
- `S.save("x.txt")` ou `S.save("x.csv")` : colonnes temps et données.
- `R.save("r.json")` ou `R.save("r.csv")` : résultats d'analyse.

## 7. Prétraitements communs

Les analyses de bruit (§8) et sur sinus (§10) partagent la même définition de la **bande d'étude** et de la **suppression du secteur**. Ces traitements sont implémentés une seule fois (`processing`) et documentés (§18.1).

### 7.1 Paramètres communs

| Paramètre | Unité | Défaut | Description |
| --- | --- | --- | --- |
| `t_start`, `t_end` | UTC | `None` | Fenêtre temporelle analysée |
| `fmin` | Hz | `0` | Borne basse de la bande d'étude (0 = pas de passe-haut) |
| `fmax` | Hz | `100` | Borne haute : passe-bas à 100 Hz par défaut |
| `remove_mains` | — | `False` | Supprimer le secteur et ses harmoniques |
| `mains_freq` | Hz | `50` | Fréquence du secteur |
| `mains_width` | Hz | `1.0` | Largeur totale supprimée autour de chaque raie (± 0,5 Hz) |
| `mains_harmonics` | — | `None` | Nombre de raies secteur traitées (`None` = toutes jusqu'à `fmax`) |
| `filter_method` | — | `"fft"` | `"fft"` (masque fréquentiel idéal) ou `"iir"` (Butterworth à phase nulle et coupe-bandes) |
| `filter_order` | — | `4` | Ordre du Butterworth (méthode `"iir"`) |
| `detrend` | — | `"constant"` | `"constant"`, `"linear"` ou `None` |
| `full_scale` | counts | `S.full_scale` | Pleine échelle PE crête-à-crête (2**24 par défaut) |
| `units` | — | `"physical"` | Unités d'affichage : `"physical"` ou `"counts"` |

Priorité des valeurs : paramètre passé à l'appel > attribut du signal (ex. `S.full_scale`) > fichier de configuration > valeur par défaut du logiciel.

### 7.2 Limitation de bande

- Si `fmax` ≥ Nyquist, aucune coupure haute n'est appliquée (la bande est limitée par l'échantillonnage) ; le résultat indique `fmax` effectif = Nyquist et un avertissement est émis.
- **Méthode `fft` (défaut)** : retrait de tendance, transformée de Fourier réelle du signal complet, mise à zéro des composantes hors de `[fmin, fmax]` (et des zones secteur si demandé), transformée inverse. Avantages : bande équivalente de bruit exacte, phase nulle, cohérence directe avec l'intégration de la DSP.
- **Méthode `iir`** : Butterworth d'ordre `filter_order` appliqué aller-retour (`sosfiltfilt`) et filtres coupe-bandes (`iirnotch`) ; suppression des bords (`edge_trim`, défaut : durée de stabilisation estimée à partir de la réponse impulsionnelle des filtres, plafonnée à 10 % de la durée). Le filtrage aller-retour réduit la bande équivalente de bruit (Butterworth d'ordre 4 : ENBW ≈ 0,90 × f_c, soit un RMS de bruit blanc inférieur d'environ 5 % à celui de la bande nominale) : l'ENBW effective est calculée et reportée.
- Le résultat indique toujours la **bande équivalente de bruit effective** (ENBW), largeurs retirées pour le secteur déduites.

### 7.3 Suppression du secteur

- Raies traitées : `k × mains_freq` pour `k = 1…K`, avec `k × mains_freq` ≤ `fmax`.
- Le résultat liste les fréquences supprimées et la largeur totale retirée.
- Option `mains_correction` (P3) : compensation, sur le RMS, de la bande retirée, sous hypothèse de bruit localement blanc.

### 7.4 Contrôles automatiques communs

- Saturation : avertissement si un échantillon atteint 99,9 % de PE/2 en valeur absolue.
- Trous : rappel des trous détectés au chargement.
- Durée insuffisante : moins de 10 périodes de `fmin`, moins de 5 périodes du sinus pour l'ajustement.
- Unité incompatible avec l'analyse (ex. `lnm` sur un signal en V) : erreur explicite.

## 8. Analyse de bruit

### 8.1 `noise(S, **params)` — P1

**Objectif** : caractériser le bruit d'un enregistrement sans signal utile (ex. numériseur entrées court-circuitées).

**Paramètres** : paramètres communs (§7.1).

**Algorithme** :

1. Sélection de la fenêtre temporelle ; calcul de la **moyenne** (offset) sur le signal brut.
2. Retrait de tendance, limitation à la bande d'étude et suppression éventuelle du secteur (§7.2, §7.3).
3. Sur le bruit ainsi filtré : **RMS** (écart-type) et **C-C** (max − min).
4. **Dynamique**, calculée en counts (la sensibilité n'intervient pas) :

   $$DR = 20\log_{10}\left(\frac{PE/(2\sqrt{2})}{\sigma_{counts}}\right)$$

   où PE/(2√2) est la valeur RMS d'un sinus pleine échelle et σ le bruit RMS en counts. Valeur de référence : un quantificateur idéal de N bits (σ = 1/√12 LSB) donne DR = 6,02·N + 1,76 dB, soit 146,26 dB pour 24 bits.

5. Grandeurs complémentaires : ENOB équivalent bruit = (DR − 1,76) / 6,02 ; C-C gaussien = 6,6 × RMS (intervalle contenant 99,9 % des échantillons d'un bruit gaussien).

**Sorties** : moyenne, RMS, C-C mesuré et C-C gaussien (en counts et en unité physique), DR (dB), ENOB équivalent bruit (bits), PE utilisée, bande effective et ENBW, raies secteur supprimées, durée analysée, nombre d'échantillons.

**Affichage** : tableau dans la console.

```text
>>> noise(S1, remove_mains=True)
Noise — S1 (RD.SN270.00.FHZ) · band 0–100 Hz · mains removed (50, 100 Hz) · 600 s
  Mean             12.31 counts  (29.35 µV)
  RMS               1.02 counts  (2.43 µV)
  Peak-to-peak      9.12 counts  (21.74 µV)
  Gaussian p-p      6.73 counts  (6.6 × RMS)
  Dynamic range   135.29 dB      (FS = 2**24 counts)
  Noise ENOB       22.18 bits
```

### 8.2 `noise_fft(S, **params)` — P1

- Spectre d'amplitude unilatéral du signal (après retrait de tendance), fenêtre `window` (défaut Hann).
- Normalisation `scale` :
  - `"amplitude"` (défaut) : amplitude crête corrigée du gain cohérent de la fenêtre — un sinus d'amplitude A apparaît avec l'amplitude A ;
  - `"rms"` : amplitude / √2 ;
  - `"asd"` : densité spectrale d'amplitude (unité/√Hz), corrigée de l'ENBW de la fenêtre — adaptée à la lecture d'un niveau de bruit ;
  - `"dbfs"` : amplitude relative à la pleine échelle.
- Figure matplotlib : fréquence en abscisse (logarithmique par défaut, linéaire en option) ; bande d'étude grisée ; raies secteur supprimées repérées ; **encadré d'informations** reprenant les résultats de `noise()` (moyenne, RMS, C-C, DR, bande, secteur) et les paramètres spectraux (fenêtre, N, résolution Δf).
- Renvoie le `Result` de `noise()` complété de la courbe spectrale.

### 8.3 `noise_dsp(S, **params)` — P1

- DSP de Welch (paramètres du §8.4), affichée en dB réf. 1 unité²/Hz ou en ASD (unité/√Hz) selon `scale`.
- Même encadré d'informations que `noise_fft`, complété du **RMS obtenu par intégration de la DSP** sur la bande d'étude (raies secteur exclues si demandé), qui doit concorder avec le RMS temporel :

  $$\sigma_{DSP} = \sqrt{\int_{f_{min}}^{f_{max}} P(f)\,df}$$

- Option (P2) : RMS cumulé en fonction de la fréquence, sur un axe secondaire, pour identifier les bandes qui dominent le bruit.

### 8.4 Paramètres spectraux communs

Utilisés par `noise_fft`, `noise_dsp`, `lnm`, `coherence` et `spectrogram`.

| Paramètre | Défaut | Description |
| --- | --- | --- |
| `window` | `"hann"` | Fenêtre de pondération (`hann`, `blackmanharris`, `flattop`…) |
| `nperseg` | plus grande puissance de 2 ≤ N/8 | Longueur des segments de Welch (≈ 15 moyennes avec 50 % de recouvrement) |
| `seg_duration` | — | Alternative à `nperseg`, en secondes |
| `overlap` | `0.5` | Taux de recouvrement des segments |
| `average` | `"mean"` | `"mean"` ou `"median"` (robuste aux transitoires) |
| `xscale` | `"log"` | Échelle de l'axe des fréquences |

## 9. Comparaison au modèle de bruit de Peterson — `lnm(S)` / `S.lnm()` — P1

**Objectif** : comparer la DSP du signal au gabarit NLNM de Peterson (1993), en tenant compte de la sensibilité et de l'unité du signal.

**Paramètres** : fenêtre temporelle ; paramètres spectraux (§8.4) ; `smoothing` (lissage en bandes de 1/n d'octave, défaut n = 8) ; `show_nhnm` (défaut `False`, modifié le 2026-11-18 à la demande) ; `x` = `"freq"` (défaut) ou `"period"`.

**Algorithme** :

1. Conversion en unités physiques : `x = counts * sensitivity`.
2. Choix de la grandeur comparée selon `S.unit` (le modèle est défini en accélération, en dB réf. 1 (m/s²)²/Hz) :

   | Unité du signal | Grandeur | Modèle utilisé |
   | --- | --- | --- |
   | `m` | déplacement | NLNM_d = NLNM_a − 40·log10(2πf) |
   | `m/s` | vitesse | NLNM_v = NLNM_a − 20·log10(2πf) |
   | `m/s**2` | accélération | NLNM_a tel quel |
   | autre (`counts`, `V`…) | — | erreur explicite invitant à renseigner `unit` et `sensitivity` de la chaîne complète |

3. DSP de Welch du signal en dB réf. 1 unité²/Hz, puis lissage.
4. Interpolation du modèle (`obspy.signal.spectral_estimation.get_nlnm()` et `get_nhnm()`) aux fréquences de la DSP, sur le domaine commun (le modèle couvre les périodes de 0,1 s à 100 000 s).
5. Écart `Δ(f) = DSP_dB(f) − NLNM_dB(f)`.

**Affichage** : une figure matplotlib à deux graphiques superposés, partageant l'axe des abscisses (logarithmique) :

- en haut : DSP du signal (brute en trait fin, lissée en trait épais), NLNM (et NHNM si `show_nhnm=True`) ;
- en bas : écart Δ en dB, avec la ligne 0 dB et les zones situées sous le NLNM mises en évidence.

**Sorties** : courbes ; écart minimal, maximal et moyen sur le domaine commun ; période (ou fréquence) de l'écart maximal ; proportion du domaine où la DSP est inférieure au NLNM.

Remarque : pour un numériseur seul (données en V), la comparaison reste possible en renseignant la sensibilité de la chaîne complète, numériseur × capteur (ex. 1 / (1500 V/(m/s) × 419 430 counts/V) ≈ 1,59·10⁻⁹ (m/s)/count) ; le manuel utilisateur décrit ce cas.

## 10. Analyses sur sinus

Les analyses de ce chapitre portent sur l'enregistrement d'un sinus de test (générateur à faible distorsion) appliqué à l'entrée de la chaîne. Elles reposent sur un même ajustement sinusoïdal et acceptent les paramètres communs du §7.1 (bande d'étude par défaut 0–100 Hz, suppression optionnelle du secteur).

Contrôle commun : un avertissement est émis si la fondamentale ou l'une de ses harmoniques coïncide avec une raie secteur.

### 10.1 Ajustement sinusoïdal 4 paramètres — `sinefit(S)` — P1

Modèle :

$$y(t_n) = A_0\cos(\omega t_n) + B_0\sin(\omega t_n) + C_0$$

Algorithme (IEEE Std 1057) :

1. Fréquence initiale : pic de la FFT fenêtrée (hors continu) avec interpolation entre bins, ou valeur `f0` fournie.
2. Ajustement 3 paramètres (A0, B0, C0) par moindres carrés à ω fixé.
3. Itérations de Gauss-Newton sur (A0, B0, C0, Δω), la colonne associée à Δω valant `−A0·t·sin(ωt) + B0·t·cos(ωt)`, jusqu'à `|Δω/ω| < tol` (défaut 1e-9) ou `maxiter` itérations (défaut 100).
4. Temps centrés sur le milieu de l'enregistrement, pour garantir le conditionnement numérique.

Sorties : amplitude crête A = √(A0² + B0²), phase, offset C0, fréquence f = ω/2π, résidu r = y − ŷ, nombre d'itérations, indicateur de convergence. Avertissement si l'enregistrement compte moins de 5 périodes ou si l'ajustement ne converge pas.

### 10.2 SINAD et ENOB — `sinad(S)` (alias `SINAD`) — P1

1. Ajustement 4 paramètres sur le signal non filtré (fenêtre temporelle choisie).
2. Limitation du résidu à la bande d'étude (défaut : passe-bas 100 Hz) et, en option, suppression du secteur et de ses harmoniques sur le résidu.
3. σ_r = RMS du résidu ainsi filtré (bruit + distorsion).

$$SINAD = 20\log_{10}\left(\frac{A/\sqrt{2}}{\sigma_r}\right) \qquad ENOB = \frac{SINAD - 1{,}76}{6{,}02}$$

ENOB ramené à la pleine échelle (les deux variantes sont publiées), équivalent à la définition IEEE 1241 `log2(PE / (σ_r·√12))` :

$$ENOB_{PE} = \frac{SINAD + 20\log_{10}\left(\frac{PE/2}{A}\right) - 1{,}76}{6{,}02}$$

**Sorties** : amplitude (counts, unité physique, dBFS), fréquence, offset, σ_r, SINAD (dB), ENOB, ENOB_PE, THD+N (= −SINAD, en dB).

**Affichage** : signal et sinus ajusté (zoom sur quelques périodes), résidu temporel, spectre du résidu avec la bande d'étude et les raies secteur ; encadré de résultats. Le spectre rappelle au-dessus du graphique les **conditions de calcul** (bande d'étude, méthode de filtrage, ENBW, 50 Hz et harmoniques supprimés ou non) ; chaque raie secteur supprimée est repérée par un **trait vertical rouge** ; l'axe des fréquences est **logarithmique** par défaut (`xscale="linear"` en option). Ces règles valent aussi pour les figures `sfdr`, `thd` et `dynamic`.

### 10.3 SFDR — `sfdr(S)` (alias `SFDR`) — P1

Mêmes paramètres et options que `sinad`, plus `window` (défaut `"blackmanharris"`) et `exclude_f0` (demi-largeur, en Hz, de la zone exclue autour de la fondamentale ; défaut : 3 fois la demi-largeur du lobe principal de la fenêtre).

1. Ajustement 4 paramètres : amplitude A, fréquence f0, résidu.
2. Spectre d'amplitude crête du résidu fenêtré, restreint à la bande d'étude, hors continu, hors zone autour de f0 et hors raies secteur si demandé. Travailler sur le résidu supprime les fuites spectrales de la fondamentale, qui masqueraient les raies faibles.
3. Plus grande raie parasite A_spur, dont l'amplitude est estimée en sommant la puissance sur son lobe principal (estimation insensible à la position de la raie entre deux bins).

$$SFDR_{dBc} = 20\log_{10}\frac{A}{A_{spur}} \qquad SFDR_{dBFS} = 20\log_{10}\frac{PE/2}{A_{spur}}$$

**Sorties** : SFDR (dBc et dBFS), fréquence de la raie parasite et sa nature (harmonique k de f0, raie secteur, autre).

**Affichage** : spectre avec la fondamentale, la raie parasite maximale repérée et la cote SFDR.

**Limite** : si aucune raie n'émerge du plancher de bruit (critère paramétrable, défaut 10 dB au-dessus du plancher médian), le SFDR mesuré est limité par ce plancher, qui dépend de N et de la fenêtre ; le résultat le signale.

### 10.4 THD — `thd(S)` (alias `THD`) — P1

Mêmes paramètres et options que `sinad`, plus `n_harmonics` (défaut 10 : harmoniques 2 à 10).

1. Ajustement 4 paramètres : fréquence f0 précise.
2. Ajustement multi-harmonique linéaire par moindres carrés (fréquences k·f0 fixées, k = 1…K) : amplitudes A_k.
3. Seules les harmoniques situées dans `[fmin, fmax]` et sous Nyquist sont retenues ; avec `remove_mains`, les harmoniques qui coïncident avec une raie secteur (à `mains_width/2` près) sont exclues et signalées.

$$THD = \frac{\sqrt{\sum_{k=2}^{K} A_k^2}}{A_1} \qquad THD_{dB} = 20\log_{10}(THD) \qquad THD_{\%} = 100 \cdot THD$$

**Sorties** : THD (dB et %), tableau des harmoniques (rang, fréquence, amplitude, dBc), harmoniques exclues.

**Affichage** : spectre avec les harmoniques repérées (H2, H3…) et tableau.

### 10.5 Analyse dynamique — `dynamic(S, noise=None, report=False)` — P1

- Un seul ajustement, réutilisé pour SINAD, ENOB, ENOB_PE, SFDR, THD et **SNR**. Le SNR utilise le résidu après retrait de la fondamentale et des harmoniques, limité à la bande d'étude :

  $$SNR = 20\log_{10}\left(\frac{A_1/\sqrt{2}}{\sigma_{bruit}}\right)$$

- Contrôle de cohérence : 10^(−SINAD/10) ≈ 10^(−SNR/10) + 10^(THD_dB/10).
- Avec un enregistrement de bruit (`noise=S_noise`), la dynamique DR (§8.1) est ajoutée à la synthèse.
- Produit un tableau de synthèse et l'ensemble des figures des §10.2 à §10.4.
- `report=True` (ou `/report` après l'analyse) génère le rapport Quarto (§14).

### 10.6 Bonnes pratiques de mesure

À reprendre dans le manuel utilisateur (§18.2) :

- choisir une fréquence de sinus qui ne soit ni un sous-multiple de la fréquence secteur (éviter 10 ; 12,5 ; 25 Hz…) ni un sous-multiple simple de la fréquence d'échantillonnage ;
- régler l'amplitude près de la pleine échelle sans saturer (ex. −1 à −3 dBFS) ;
- enregistrer au moins plusieurs dizaines de périodes, sur une durée compatible avec la résolution spectrale visée.

## 11. Mesures temporelles — P2

Chaque mesure est une fonction distincte. Les instants de passage sont déterminés avec une précision inférieure à l'échantillon, par interpolation linéaire.

### 11.1 Fréquence — `frequency(S, method="zero_crossing")`

- `zero_crossing` (défaut) : passages montants par le niveau moyen, avec hystérésis (défaut 5 % du C-C) pour éviter les déclenchements multiples dus au bruit ; fréquence = nombre de périodes complètes / durée entre le premier et le dernier passage retenus.
- `sinefit` : fréquence issue de l'ajustement 4 paramètres (sinus uniquement, méthode la plus précise).
- `fft` : pic spectral interpolé.

Sorties : fréquence (Hz), dispersion des fréquences période par période, nombre de périodes.

### 11.2 Période — `period(S, method="zero_crossing")`

Mêmes détecteurs. Sorties : période moyenne, écart-type, minimum, maximum, nombre de périodes, liste des périodes.

### 11.3 Temps de passage à 50 % entre deux signaux — `delay50(S1, S2)`

Mesure du décalage temporel entre deux signaux au passage de 50 % de leur amplitude, comme sur un oscilloscope : échelon ou impulsion appliqué simultanément sur deux voies, synchronisation de deux numériseurs par PPS.

1. Pour chaque signal : niveaux bas et haut par la méthode de l'histogramme (option : min/max), seuil x50 = bas + 0,5 × (haut − bas).
2. Instants de passage par interpolation linéaire entre les échantillons n et n+1 :

   $$t_c = t_n + \frac{x_{50} - x_n}{x_{n+1} - x_n}\,\Delta t$$

3. Calcul en temps absolu (UTC) : les deux signaux peuvent avoir des fréquences d'échantillonnage différentes, mais doivent se recouvrir temporellement.
4. Appariement de chaque front de S1 avec le front de S2 le plus proche : Δt = t(S2) − t(S1).

Options : `edge` = `"rising"`, `"falling"` ou `"both"` ; `level` (défaut 0,5, pour mesurer à un autre seuil) ; `hysteresis`.

Sorties : Δt moyen, écart-type, minimum, maximum, nombre de fronts, liste des Δt. Affichage : superposition des deux signaux autour d'un front, instants de passage repérés.

## 12. Cohérence et spectrogramme — P2

### 12.1 Cohérence — `coherence(S1, S2, **params)`

- Cohérence quadratique moyenne estimée par la méthode de Welch (`scipy.signal.coherence`) :

  $$C_{xy}(f) = \frac{|P_{xy}(f)|^2}{P_{xx}(f)\,P_{yy}(f)}$$

- Les signaux sont ramenés sur leur fenêtre commune et sur la même grille temporelle (mêmes règles que l'addition, §5.1).
- Paramètres spectraux communs (§8.4).
- Figure matplotlib : cohérence (0 à 1) en fonction de la fréquence (échelle logarithmique). Option P3 : seuil de signification statistique 1 − α^(1/(n−1)), n étant le nombre de segments indépendants (α = 0,05 par défaut).
- Sorties : courbe, nombre de moyennes, cohérence moyenne dans la bande d'étude.

### 12.2 Spectrogramme — `spectrogram(S, **params)`

- Transformée de Fourier à court terme ; par défaut, fenêtre de Hann de 2^k échantillons (k choisi pour obtenir environ 100 tranches temporelles) et recouvrement de 50 %.
- Échelle en dB réf. 1 unité²/Hz ; axe des fréquences linéaire ou logarithmique ; bornes de couleur automatiques (percentiles 1 et 99 %) ou imposées ; bande `fmin` – `fmax`.
- Figure : spectrogramme avec barre de couleur et temps UTC ; option : signal temporel au-dessus, avec axe des temps partagé.

## 13. Acquisition et temps réel SeedLink

### 13.1 Acquisition — refonte de `acq_mseed.py` — P1

**Existant.** Le script actuel interroge le serveur (`INFO STREAMS`), liste les voies disponibles pour un réseau et une station, laisse l'utilisateur les choisir, acquiert le flux dans un thread pendant une durée donnée avec une barre de progression, puis fusionne les données, les écrit en miniSEED et affiche N, moyenne et écart-type par voie. Ce fonctionnement est conservé et amélioré comme suit :

| Constat sur le script actuel | Amélioration demandée |
| --- | --- |
| Serveur, réseau, station, durée et fichier de sortie codés en dur (avec des affectations en double) | Arguments de ligne de commande ; valeurs par défaut dans la configuration |
| Trous comblés silencieusement (`merge(method=1, fill_value="interpolate")`) : un bruit mesuré sur une portion interpolée est faux | Trous détectés, journalisés et affichés ; politique de comblement explicite (§6.1) |
| Données gardées en mémoire et écrites uniquement à la fin : tout est perdu en cas d'arrêt brutal | Écriture incrémentale sur disque au fil de l'eau ; fichier final consolidé en fin d'acquisition |
| Progression exprimée en nombre de paquets (« traces ») reçus | Progression par voie : échantillons reçus, heure du dernier échantillon, latence, trous, fréquence effective |
| Durée mesurée en temps horloge depuis le lancement | Option d'arrêt sur la durée des données reçues ou sur une fenêtre début / fin |
| Code exécuté au niveau du module | Module importable (`acquire(...)`) et point d'entrée CLI, utilisables par la console (`/acq`) et, en phase 2, par le web (R7) |
| Fermeture du client pendant que le thread de réception tourne | Arrêt propre (fin de durée ou Ctrl+C) : fermeture de la connexion, attente du thread, sauvegarde des données reçues |
| Pas de reprise sur coupure réseau | Reconnexion automatique (nombre d'essais et délai configurables) |

**Interface** :

```text
onthesignal acq --server 10.16.0.163 [--port 18000] --network RD --station SN270 \
                [--channels "FH?"] [--duration 110 | --start <UTC> --end <UTC>] \
                [--outdir data/] [--output "{net}.{sta}.{loc}.{cha}_{start}.mseed"] [--load]
```

- Sans `--channels` : liste des voies disponibles et sélection interactive (comportement actuel).
- Affichage temps réel dans le terminal : barre de progression globale (temps écoulé / durée, pourcentage), tableau par voie (échantillons, dernier échantillon UTC, latence, trous, fréquence effective), état de la connexion, taille du fichier.
- En fin d'acquisition : résumé par voie (N, moyenne, écart-type, C-C, trous) et chemin du fichier ; avec `--load`, chargement des signaux dans la session.
- Depuis la console, `/acq` s'exécute au premier plan avec le même affichage ; exécution en tâche de fond avec avancement dans la barre d'état — P3.
- Journalisation dans un fichier.

### 13.2 Analyse temps réel — `realtime(...)` / `/rt` — P2

- Connexion SeedLink et sélection des voies avec le même module client que l'acquisition.
- Tampon circulaire par voie, de durée configurable.
- Mesures limitées à :
  - moyenne, écart-type et C-C sur fenêtre glissante (durée et période de rafraîchissement configurables, défaut 10 s et 1 s), présentés dans un tableau rafraîchi dans le terminal, en counts et en unité physique ;
  - FFT et DSP de Welch sur fenêtre glissante (défaut 60 s), dans une figure matplotlib rafraîchie (défaut toutes les 2 s).
- Affichage de la latence et des trous ; arrêt par `q` ou Ctrl+C ; enregistrement simultané en miniSEED en option (réutilise le §13.1).
- Réception, calcul et affichage découplés (R7).

## 14. Rapports — P1

`report(results, title=None, output_dir="reports/", formats=("html", "pdf"), render=False)` — commande `/report`.

- Génère un dossier `reports/YYYY-MM-DD_hhmm_<title>/` contenant `report.qmd` et un sous-dossier `figures/` (PNG 200 dpi ; SVG en option).
- Contenu :
  1. en-tête YAML (titre, auteur, date, formats HTML et PDF) ;
  2. contexte (texte libre, extrait optionnel du fichier de contexte utilisateur) ;
  3. signaux analysés : NSLC, fs, durée, unité, sensibilité, source, empreinte SHA-256, trous ;
  4. paramètres utilisés ;
  5. résultats (tableaux avec unités) et figures légendées ;
  6. historique des traitements, versions des logiciels (onthesignal, numpy, scipy, ObsPy) ;
  7. conclusion (texte libre ; synthèse proposée par l'IA en option, signalée comme telle — P3).
- Modèle personnalisable (`templates/report.qmd.j2` : logo, en-tête du laboratoire…). Les rapports sont générés en anglais (§3.2).
- `render=True` lance `quarto render` si Quarto est installé ; sinon, le logiciel indique la commande à exécuter. Moteur PDF configurable (`[report] pdf_engine`) : Typst par défaut (fourni avec Quarto, sans installation supplémentaire) ou LaTeX (TinyTeX).
- Utilisable avec tout `Result` (bruit, LNM, analyse dynamique…) ; l'analyse dynamique en est le cas d'usage principal.

## 15. Interface terminal (IHM) — P1

### 15.1 Lancement

- `onthesignal` : console interactive ;
- `onthesignal data/*.mseed` : console avec chargement initial des fichiers ;
- `onthesignal run scripts/my_analysis.py [arguments]` : exécution non interactive ;
- `onthesignal acq …` : acquisition (§13.1).

### 15.2 Modes de saisie

| Saisie | Effet |
| --- | --- |
| `/command [arguments]` | Commande du registre (R8) |
| Expression Python | Exécutée dans l'espace de noms de la session : `noise(S1, fmax=50)`, `S3 = S1 + S2`, `list_sig()` |
| `/ai` | Bascule en mode IA : les saisies suivantes sont adressées au modèle ; `/ai` à nouveau pour revenir au mode Python |
| `/ai <question>` | Question ponctuelle à l'IA, sans changer de mode |

Ergonomie inspirée d'opencode :

- la frappe de `/` ouvre un menu de toutes les commandes avec une description courte, filtré au fil de la frappe (recherche approximative) ;
- complétion des noms de signaux, de scripts, de paramètres et de chemins ; historique persistant ; coloration syntaxique ;
- barre d'état : mode (Python / IA), nombre de signaux, modèle IA actif, acquisition en cours, répertoire de travail ;
- une erreur n'interrompt jamais la console : message clair (en anglais), trace complète avec `/debug on` ;
- les fenêtres matplotlib sont non bloquantes : la console reste utilisable pendant l'affichage.

### 15.3 Formulaires de paramètres

- Une commande d'analyse lancée sans paramètre (ex. `/noise S1`) ouvre un formulaire généré à partir de la déclaration des paramètres (R3). Chaque champ affiche sa valeur par défaut — par exemple `Full scale, peak-to-peak (counts) [2**24]` — et Entrée la valide.
- Les expressions arithmétiques simples (`2**23`, `1e-3`) sont acceptées grâce à un évaluateur sécurisé (pas d'`eval` libre).
- Les paramètres peuvent aussi être passés en ligne (`/noise S1 fmax=50 remove_mains=true`) ; `--defaults` saute le formulaire.

### 15.4 Commandes principales

| Commande | Équivalent Python | Rôle | Priorité |
| --- | --- | --- | --- |
| `/help [command]` | `help(function)` | Aide générale ou détaillée | P1 |
| `/load <file> [options]` | `load(...)` | Charger un miniSEED ou un fichier texte | P1 |
| `/list` | `list_sig()` | Lister les signaux | P1 |
| `/info <S>` | `S.print()` | Paramètres d'un signal | P1 |
| `/show <S>` | `S.show()` | Tracé temporel | P1 |
| `/noise`, `/noise_fft`, `/noise_dsp` | `noise(S)`… | Analyse de bruit (§8) | P1 |
| `/lnm <S>` | `lnm(S)` | Comparaison au NLNM (§9) | P1 |
| `/sinad`, `/sfdr`, `/thd` | `sinad(S)`… | Analyses sur sinus (§10) | P1 |
| `/dynamic <S> [noise]` | `dynamic(S)` | Analyse dynamique complète (§10.5) | P1 |
| `/report` | `report(...)` | Rapport Quarto (§14) | P1 |
| `/acq` | `acquire(...)` | Acquisition SeedLink (§13.1) | P1 |
| `/edit_script <name>` | — | Créer ou éditer un script (vi / nano) | P1 |
| `/run_script <name> [S…] [p=v…]` | — | Exécuter un script | P1 |
| `/quit` | — | Quitter | P1 |
| `/rename`, `/rm` | `rename_sig()`, `rm_sig()` | Gestion des signaux | P2 |
| `/export <S> <file>` | `S.save()` | Export miniSEED ou texte | P2 |
| `/frequency`, `/period` | `frequency(S)`, `period(S)` | Mesures (§11) | P2 |
| `/delay50 <S1> <S2>` | `delay50(S1, S2)` | Délai à 50 % (§11.3) | P2 |
| `/coherence <S1> <S2>` | `coherence(S1, S2)` | Cohérence (§12.1) | P2 |
| `/spectrogram <S>` | `spectrogram(S)` | Spectrogramme (§12.2) | P2 |
| `/rt` | `realtime(...)` | Analyse temps réel (§13.2) | P2 |
| `/scripts` | — | Lister les scripts | P2 |
| `/batch <processing> <files>` | — | Traitement par lots (§16.2) | P2 |
| `/ai [question]` | — | Mode IA ou question ponctuelle (§17) | P2 |
| `/ai_script <name> "<description>"` | — | Génération de script par l'IA (§17.6) | P2 |
| `/init [folder]` | — | Construire le contexte de l'IA (§17.4) | P2 |
| `/context` | — | Éditer le fichier de contexte utilisateur (§17.5) | P2 |
| `/model` | — | Choisir le fournisseur et le modèle d'IA | P2 |
| `/config` | — | Afficher ou modifier la configuration | P2 |
| `/debug on`, `/debug off` | — | Traces complètes des erreurs | P3 |

### 15.5 Édition de scripts

- `/edit_script <name>` ouvre `scripts/<name>.py` dans l'éditeur configuré (`editor` dans la configuration, à défaut `$EDITOR`, à défaut `nano` ; `vi` au choix). Si le script n'existe pas, il est créé à partir du modèle (§16.1).
- À la fermeture de l'éditeur : vérification syntaxique et rechargement du script ; en cas d'erreur, affichage et proposition de rééditer.

### 15.6 Scénario type

```text
$ onthesignal data/acquisition_FHZ.mseed
onthesignal 1.0 — 3 signals loaded (S1, S2, S3). Type / to list commands.
ots> S1.sensitivity = 2.384e-6; S1.unit = "V"   # 40 V p-p / 2**24 counts
ots> noise(S1, remove_mains=True)               # results table
ots> /noise_dsp S1                              # pre-filled form, then figure
ots> /dynamic S2                                # SINAD, ENOB, SFDR, THD, SNR + figures
ots> /report                                    # .qmd report + figures
ots> S3.sensitivity = 1.59e-9; S3.unit = "m/s"  # 1 / (1500 V/(m/s) × 419430 counts/V)
ots> /ai is the noise of S3 below the NLNM?
```

## 16. Scripts standardisés et traitements par lots — P1

Objectif : écrire des traitements réutilisables selon une structure unique, pour les enchaîner en série et les appeler indifféremment depuis la console, l'IA et, en phase 2, le web.

### 16.1 Modèle de script — `templates/script_template.py`

```python
"""
Name        : my_analysis
Description : <what the script computes, in one sentence>
Author      : <name>
Version     : 1.0 — YYYY-MM-DD
Inputs      : 1 signal (any unit)
"""
from onthesignal import Signal, Result, Param

# Declared parameters: console form, help, AI tool, (phase 2) web form
PARAMS = [
    Param("fmax", float, 100.0, unit="Hz", help="Upper bound of the analysis band"),
    Param("remove_mains", bool, False, help="Remove 50 Hz mains and its harmonics"),
]


def run(signals: list[Signal], **params) -> Result:
    """Pure computation: no display, no file output."""
    s = signals[0]
    ...
    return Result(kind="my_analysis", signals=signals, params=params,
                  values={...}, curves={...})


def plot(result: Result):
    """Optional: return a matplotlib figure built from the result."""
    ...


if __name__ == "__main__":
    # Standalone run: python scripts/my_analysis.py --files data/*.mseed --out results.csv
    from onthesignal.scripts import main
    main(run, PARAMS, plot)
```

Règles :

- `run()` ne fait que calculer et renvoie un `Result` (R2) ; `plot()` est facultative ;
- les paramètres sont déclarés dans `PARAMS` (formulaire, aide et schéma IA automatiques) ;
- tout script placé dans `scripts/` est découvert automatiquement : il apparaît dans `/scripts`, s'exécute par `/run_script <name> S1 [param=value…]` et est proposé à l'IA comme outil (P2) ;
- un script est aussi exécutable seul : `python scripts/my_analysis.py --files data/*.mseed --out results.csv`.

### 16.2 Traitements par lots — P2

- `/batch <script|analysis> <files|glob> [param=value…] --out results.csv` exécute le traitement sur chaque fichier et chaque voie, puis agrège les `values` dans un tableau (une ligne par fichier et par voie) au format CSV ou JSON ; rapport global en option.
- Une erreur sur un fichier n'interrompt pas le lot : elle est consignée dans le tableau et dans le journal.

## 17. Assistant IA — P2

### 17.1 Fournisseurs

- Claude (API Anthropic), ChatGPT (API OpenAI) et modèles locaux Ollama, derrière une interface commune (`LLMProvider.chat(messages, tools)`).
- Choix du fournisseur et du modèle dans la configuration ou par `/model`.
- Clés d'API lues dans les variables d'environnement (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`), jamais écrites dans les fichiers du projet.
- Appel d'outils (*tool calling*) lorsque le modèle le permet ; à défaut, le modèle propose du code Python que l'utilisateur valide avant exécution.

### 17.2 Fichier `agent.md` destiné à l'IA

- `docs/ai/agent.md`, rédigé en anglais, décrit chaque fonction exposée : rôle, **quand l'utiliser** (formulations types : « show the noise and compare it to the LNM » → `lnm(S)`), signature, paramètres (défauts, unités), sorties, exemple.
- Ce fichier et les schémas d'outils sont **générés automatiquement** à partir du registre des commandes et des docstrings (R3, R8) — commande `/gen_ai_doc` et étape de construction de la documentation — afin de rester synchronisés avec le code. Une section rédigée à la main peut le compléter.

### 17.3 Contexte transmis au modèle

- Invite système, en anglais : rôle (assistant de caractérisation de chaînes sismiques), conventions (§3.2), résumé des algorithmes (issu de `docs/algorithms/`), règles de sécurité.
- État de la session : signaux et métadonnées, derniers résultats (`to_dict()`).
- Outils d'inspection (`list_signals`, `signal_info`, `get_result`…) permettant au modèle d'aller chercher l'information nécessaire à l'analyse plutôt que de tout recevoir d'emblée.
- Le modèle reçoit des **résumés** (statistiques, courbes décimées), pas les échantillons bruts.

Exemple :

```text
ai> show the noise of S3 and compare it to the LNM
  → signal_info(S3) : unit m/s, sensitivity set
  → lnm(S3)         : figure displayed; max deviation +4.1 dB around 0.2 s
  ← "S3 noise is below the NLNM between 1 and 30 s, but exceeds it by 4 dB around 0.2 s…"
```

### 17.4 `/init`

- Parcourt tous les signaux de la session (et, avec `/init <folder>`, les fichiers de données de ce dossier) et calcule pour chacun : métadonnées, durée, trous, moyenne, RMS, C-C, saturation, principales raies spectrales, nature probable (bruit, sinus avec fréquence et amplitude, échelon, autre).
- Écrit le résultat dans `.onthesignal/init_context.md` (lisible et modifiable), chargé dans le contexte de l'IA.

### 17.5 Fichier de contexte utilisateur

- `context.md`, à la racine du projet, édité par `/context` (ouverture dans l'éditeur) : banc de test, numériseur et réglages (gain, fréquence d'échantillonnage, filtres), capteur, performances attendues (ex. DR > 135 dB), procédure, conventions de nommage.
- Toujours inclus dans le contexte de l'IA ; un fichier global optionnel (`~/.config/onthesignal/context.md`) peut s'y ajouter.

### 17.6 Génération de scripts par l'IA

- `/ai_script <name> "<description>"` utilise une invite dédiée contenant le modèle de script (§16.1), la référence de l'API et les règles de codage.
- Le script produit respecte le modèle, porte l'en-tête « Generated by AI (provider, model, date) — review before use », est enregistré dans `scripts/<name>.py`, vérifié syntaxiquement, puis présenté à l'utilisateur (`/edit_script`) avant toute exécution.

### 17.7 Sécurité et confidentialité

- Exécution automatique limitée aux fonctions d'analyse en lecture seule (configurable).
- Confirmation obligatoire pour : écriture ou suppression de fichiers, exécution d'un script, lancement d'une acquisition, exécution de code Python proposé par le modèle (toujours affiché au préalable).
- Aucune commande système arbitraire.
- Fournisseurs en ligne : seuls les métadonnées et les résultats sont transmis ; les échantillons bruts ne le sont que si `send_raw_data = true`. Ollama permet un fonctionnement entièrement local.
- Toutes les actions de l'IA sont journalisées et apparaissent dans l'historique et dans les rapports.

## 18. Documentation — livrable obligatoire (P1)

> La documentation fait partie du produit. **Aucune fonctionnalité n'est considérée comme terminée sans sa documentation** (§18.5).
>
> Elle couvre trois volets : **les algorithmes** (§18.1), **le fonctionnement du logiciel** (manuel utilisateur, §18.2) et **la conception** (documentation développeur, §18.3). Elle est rédigée **en anglais**, au format Quarto (`.qmd` et Markdown, équations LaTeX), versionnée avec le code dans `docs/` et construite automatiquement par Quarto sous forme de site web (export PDF possible) ; la référence de l'API est générée à partir des docstrings par quartodoc.

### 18.1 Documentation des algorithmes — `docs/algorithms/`

Une page par algorithme ou famille d'algorithmes :

- prétraitements : retrait de tendance, limitation de bande (FFT et IIR), suppression du secteur, ENBW ;
- FFT et normalisations : amplitude, RMS, ASD, dBFS, fenêtres, gain cohérent, ENBW ;
- DSP de Welch, RMS par intégration, lissage en fraction d'octave ;
- bruit : moyenne, RMS, C-C, dynamique, ENOB équivalent bruit ;
- comparaison NLNM / NHNM, conversions déplacement / vitesse / accélération ;
- ajustement sinusoïdal 3 et 4 paramètres ;
- SINAD, ENOB, SNR, THD, SFDR, analyse dynamique ;
- fréquence, période, délai à 50 % ;
- cohérence, spectrogramme ;
- opérations sur les signaux (interpolation, rééchantillonnage) ;
- statistiques glissantes temps réel.

Chaque page comporte obligatoirement :

1. l'objectif et la définition de la grandeur mesurée ;
2. le principe et les équations, avec notations et unités ;
3. les hypothèses et le domaine de validité (stationnarité, durée minimale, nombre de périodes, niveau de signal…) ;
4. la mise en œuvre numérique : étapes, fonctions numpy / scipy / ObsPy utilisées, valeurs par défaut et leur justification, normalisations, traitement des bords ;
5. les limites connues, biais et incertitudes (ex. dépendance du C-C à la durée, ENBW d'un filtre aller-retour, biais de la cohérence estimée, plancher de bruit du SFDR) ;
6. la validation : cas de test sur signaux synthétiques, résultats attendus et tolérances, reliés aux tests automatiques (§19) ;
7. un exemple commenté avec figure, produite par une cellule de code Python exécutée au rendu Quarto (exemple toujours reproductible et à jour) ;
8. les références bibliographiques (annexe A).

### 18.2 Documentation de fonctionnement — manuel utilisateur — `docs/user/`

- installation (Python, dépendances, Quarto, éditeur) et premier lancement ;
- configuration : référence complète du fichier de configuration, clés d'API, serveurs SeedLink ;
- prise en main pas à pas : charger un fichier → `list_sig()` → `S.print()` → `noise()` → `lnm()` → `dynamic()` → rapport ;
- conventions : unités, sensibilité, dB, dBFS, signe du délai, temps UTC ;
- formats de fichiers : miniSEED, texte (exemples commentés), export ;
- référence de toutes les commandes `/` et fonctions Python, générée depuis les docstrings et le registre (même contenu que `/help`) ;
- modes opératoires de mesure : bruit propre d'un numériseur, essais sur sinus, comparaison au NLNM (montage, durée, choix de la fréquence et de l'amplitude, pièges courants — §10.6) ;
- acquisition et temps réel ;
- scripts : modèle, édition, exécution, traitements par lots ;
- rapports : génération, rendu PDF / HTML, personnalisation du modèle ;
- assistant IA : configuration, utilisation, fichiers de contexte, règles de sécurité et de confidentialité, limites ;
- dépannage, FAQ et liste des messages d'erreur.

### 18.3 Documentation développeur — `docs/developer/`

- architecture (couches, dépendances, règles R1 à R9) et modèle de données (`Signal`, `Result`, `Param`, `Session`, registre) ;
- procédure « ajouter une analyse » : calcul, paramètres, résultat, rendu, commande, page d'algorithme, tests, exposition à l'IA ;
- conventions de code : PEP 8, ruff, annotations de type, docstrings, journalisation, gestion des erreurs ;
- tests et validation, intégration continue, publication (versionnement sémantique, `CHANGELOG.md`) ;
- règles de compatibilité avec la phase 2 (web).

### 18.4 Docstrings

- Obligatoires pour toute fonction, classe et méthode publique, au format NumPy, en anglais : description, paramètres (type, défaut, unité), valeur renvoyée, exceptions, notes (résumé de l'algorithme et renvoi vers sa page), exemples exécutables (doctest).
- Source unique de la référence de l'API (quartodoc), de l'aide `/help` et du fichier `agent.md` (§17.2).

### 18.5 Définition de « terminé »

Une fonctionnalité est terminée lorsque :

- [ ] le code respecte les règles R1 à R9 et passe les contrôles qualité (ruff, mypy) ;
- [ ] les docstrings sont complètes ;
- [ ] les tests unitaires et de validation passent (§19) ;
- [ ] la page d'algorithme est rédigée (pour toute fonctionnalité de calcul) ;
- [ ] le manuel utilisateur est à jour (commande, exemple) ;
- [ ] le fichier `agent.md` est régénéré ;
- [ ] le `CHANGELOG.md` est complété.

La construction de la documentation (liens, exemples exécutables) est vérifiée en intégration continue.

## 19. Qualité, tests et validation — P1

- Tests automatiques avec pytest ; couverture ≥ 80 % sur `core`, `io`, `processing` et `analysis`.
- Validation sur signaux synthétiques de caractéristiques connues. Les tolérances ci-dessous sont indicatives et seront confirmées dans les pages d'algorithme (§18.1).

| ID | Cas de test | Résultat attendu | Tolérance |
| --- | --- | --- | --- |
| V-01 | Bruit blanc gaussien σ = 100 counts, fs = 200 Hz, 10⁶ échantillons, bande complète | `noise` : RMS = 100 counts | ± 1 % |
| V-02 | Même signal | RMS par intégration de la DSP = RMS temporel | ± 2 % |
| V-03 | Bruit uniforme de quantification idéale (σ = 1/√12 LSB), PE = 2**24, bande complète | DR = 146,26 dB | ± 0,1 dB |
| V-04 | Sinus idéal quantifié sur N = 16 et 24 bits, proche de la pleine échelle, bande complète | ENOB_PE = N | ± 0,1 bit |
| V-05 | Sinus d'amplitude A + bruit blanc σ, bande complète | SINAD = 20·log10((A/√2)/σ) | ± 0,1 dB |
| V-06 | Sinus + harmoniques H2 et H3 d'amplitudes connues | THD = √(A2² + A3²)/A1 | ± 0,1 dB |
| V-07 | Sinus + raie parasite non harmonique d'amplitude connue | SFDR et fréquence de la raie | ± 0,2 dB ; ± 1 bin |
| V-08 | Sinus sans bruit, 7,3 périodes, fréquence hors bin | `sinefit` retrouve f, A, phase, offset | erreur relative < 1e-6 |
| V-09 | Bruit blanc de DSP connue (2σ²/fs) en m/s² | DSP mesurée par `lnm` ; NLNM converti en vitesse et en déplacement selon le §9 | ± 0,5 dB ; < 0,01 dB |
| V-10 | Deux bruits identiques ; deux bruits indépendants | cohérence = 1 ; cohérence moyenne ≈ 1/n (n moyennes) | ± 0,01 ; < 3/n |
| V-11 | Rampes linéaires de 10 échantillons décalées de 0,37 Δt, fréquences d'échantillonnage différentes | `delay50` = décalage imposé | ± 0,01 Δt |
| V-12 | Sinus pur, ≥ 100 périodes, ≥ 10 échantillons par période | `frequency`, `period` | erreur relative < 1e-4 |
| V-13 | Sinus d'amplitude A centré sur un bin | `noise_fft` (`scale="amplitude"`) affiche A | ± 0,1 % |
| V-14 | `S1 + S2` avec un décalage d'un demi-échantillon | fenêtre commune et interpolation correctes, avertissement émis | exact |
| V-15 | Fichier miniSEED comportant un trou | trou détecté, politique appliquée, trou signalé | — |
| V-16 | Fichier texte à virgule décimale ; fichier à colonne de temps irrégulière | lecture correcte ; erreur explicite | — |

- Jeux de données réels de référence (`tests/data/`) pour la non-régression ; comparaison croisée avec un outil de référence lorsque c'est possible.

## 20. Exigences non fonctionnelles

| Domaine | Exigence |
| --- | --- |
| Plateforme | Linux ; Python ≥ 3.11 |
| Installation | Paquet décrit par `pyproject.toml`, installable par `pip install -e .` ; dépendances optionnelles `[ai]`, `[web]`, `[dev]` ; commande `onthesignal` |
| Performances | Pour un signal de 10⁷ échantillons (ex. 24 h à 100 éch/s), chargement, `noise`, `noise_dsp`, `lnm` et `sinad` en moins de 10 s chacun sur un poste de travail courant ; tracé des longues séries par décimation |
| Mémoire | Données en float64 (8 octets par échantillon) ; avertissement au-delà d'un seuil configurable |
| Configuration | `~/.config/onthesignal/config.toml` (global), surchargé par `./onthesignal.toml` (projet) |
| Journalisation | Module `logging` ; fichiers dans `.onthesignal/logs/` ; niveau configurable |
| Robustesse | Messages d'erreur explicites (en anglais), avec piste de résolution ; aucune erreur ne ferme la console |
| Hors ligne | Toutes les fonctions sont utilisables sans réseau, sauf SeedLink et IA en ligne |
| Traçabilité | Version, paramètres, empreinte des fichiers et historique dans chaque résultat et chaque rapport (R9) |
| Gestion de version | Dépôt git, versionnement sémantique, `CHANGELOG.md` |

Exemple de fichier de configuration :

```toml
[analysis]
fmax = 100.0
mains_freq = 50.0
full_scale = 16777216      # 2**24

[console]
editor = "nano"            # or "vi"
mpl_backend = "QtAgg"

[seedlink]
server = "10.16.0.163"
port = 18000

[ai]
provider = "ollama"        # "anthropic", "openai" or "ollama"
model = "<model name>"
base_url = ""              # serveur Ollama distant, ex. http://gb10:11434
context = 0                # contexte Ollama en tokens (num_ctx) ; 0 = défaut du serveur
auto_execute = "read_only"
send_raw_data = false

[report]
pdf_engine = "typst"       # or "latex" (TinyTeX)
```

## 21. Organisation du code et lots de développement

### 21.1 Arborescence proposée

```text
onthesignal/
├── pyproject.toml
├── README.md
├── CHANGELOG.md
├── context.md               # contexte utilisateur pour l'IA (§17.5)
├── src/onthesignal/
│   ├── core/                # Signal, Result, Param, Session, unités, registre des commandes
│   ├── io/                  # miniSEED, texte, export
│   ├── processing/          # tendance, bande d'étude, secteur, fenêtres, décimation
│   ├── analysis/            # noise, spectral, lnm, sinefit, sinad, sfdr, thd, dynamic,
│   │                        # measures, coherence, spectrogram
│   ├── plot/                # rendus matplotlib des Result
│   ├── report/              # génération des rapports .qmd
│   ├── seedlink/            # client commun, acquisition (ex-acq_mseed.py), temps réel
│   ├── ai/                  # fournisseurs, outils, contexte, invites
│   └── cli/                 # console, commandes « / », formulaires, éditeur
├── templates/               # script_template.py, report.qmd.j2
├── scripts/                 # scripts utilisateur
├── docs/                    # site Quarto (§18)
│   ├── _quarto.yml
│   ├── algorithms/          # une page par algorithme (§18.1)
│   ├── user/                # manuel utilisateur (§18.2)
│   ├── developer/           # documentation développeur (§18.3)
│   ├── reference/           # référence de l'API, générée par quartodoc
│   └── ai/                  # agent.md, généré (§17.2)
├── examples/                # fichiers d'exemple (miniSEED, texte)
└── tests/                   # tests unitaires et de validation, données de test
```

### 21.2 Lots de développement

Chaque lot livre son code, ses tests, ses pages d'algorithmes et sa documentation utilisateur (définition de « terminé », §18.5).

| Lot | Contenu | Priorité |
| --- | --- | --- |
| 0 | Socle : arborescence, `pyproject.toml`, outils qualité (ruff, mypy, pytest), squelette de la documentation (site Quarto + quartodoc), intégration continue | P1 |
| 1 | `Signal`, `Result`, `Param`, `Session`, registre ; lecture miniSEED et texte ; `list_sig`, `print`, `show`, opérateurs ; console minimale (Python, `/help`, `/load`, `/list`) | P1 |
| 2 | Prétraitements communs ; `noise`, `noise_fft`, `noise_dsp` ; `lnm` | P1 |
| 3 | `sinefit`, `sinad` / ENOB, `sfdr`, `thd`, SNR, `dynamic` ; rapports Quarto | P1 |
| 4 | Console complète : menu `/`, formulaires, barre d'état ; scripts (modèle, édition vi / nano, exécution) ; lots | P1 |
| 5 | Refonte de l'acquisition (`acq_mseed.py`) | P1 |
| 6 | Mesures (`frequency`, `period`, `delay50`), `coherence`, `spectrogram` | P2 |
| 7 | Temps réel SeedLink | P2 |
| 8 | Assistant IA : fournisseurs, outils, fichier `agent.md`, `/init`, contexte, génération de scripts | P2 |
| Phase 2 | Interface web NiceGUI 4 + µPlot — cahier des charges séparé, `onthesignal_web.md` | — |

## 22. Décisions sur les points ouverts

Les points ouverts de la v2 ont été tranchés le 2026-11-17. Ces décisions sont intégrées dans le corps du document (v2.1).

| # | Sujet | Décision |
| --- | --- | --- |
| 1 | Convention de sensibilité | Coefficient multiplicatif en unité physique par count : `physical = counts * sensitivity`. À l'intégration de StationXML (sensibilité en counts par unité), la valeur lue sera inversée (§3.2) |
| 2 | Trous dans les fichiers miniSEED | Conserver le plus long segment continu ; trous toujours signalés, jamais comblés silencieusement (§6.1) |
| 3 | Méthode de limitation de bande | Masque FFT par défaut ; Butterworth aller-retour en option (§7.2) |
| 4 | `detrend` par défaut | Retrait de la moyenne seule, `"constant"` (§7.1) |
| 5 | `lnm` | Axe en fréquence (modifié le 2026-11-18, à la demande ; `x="period"` reste disponible) ; lissage 1/8 d'octave ; NHNM masqué par défaut (modifié le 2026-11-18 ; `show_nhnm=True` pour l'afficher) (§9) |
| 6 | ENOB | ENOB (relatif au sinus mesuré) et ENOB_PE (ramené à la pleine échelle) publiés tous les deux (§10.2) |
| 7 | THD | Harmoniques 2 à 10 situées dans la bande d'étude (§10.4) |
| 8 | `delay50` | Fonctionnement générique du §11.3 (échelon, impulsion ou PPS), appariement avec le front le plus proche |
| 9 | Rendu PDF des rapports | Deux moteurs supportés : Typst par défaut (fourni avec Quarto), LaTeX (TinyTeX) en option (§14) |
| 10 | IA | Ollama (local) par défaut ; exécution automatique des seules analyses en lecture seule ; pas d'envoi des échantillons bruts (§17.7) |
| 11 | Langue | Tout le logiciel en anglais, sans texte en français : code, interface, documentation, `agent.md` et rapports. Le présent cahier des charges reste en français (§3.2) |
| 12 | Noms de fonctions | Minuscules (`sinad`, `sfdr`, `thd`) et alias en majuscules (`SINAD`, `SFDR`, `THD`) (§3.2) |
| 13 | Volumétrie et performances | Signaux jusqu'à 10⁷ échantillons ; moins de 10 s par analyse (§20) |
| 14 | Outil de documentation | Quarto (site web, export PDF possible) ; référence de l'API générée par quartodoc (§18) |
| 15 | Priorités et ordre des lots | Validés tels que proposés (§2.1, §21.2) |

## Annexe A — Références

- IEEE Std 1057-2017, *IEEE Standard for Digitizing Waveform Recorders* (ajustements sinusoïdaux 3 et 4 paramètres).
- IEEE Std 1241-2010 (ou révision en vigueur), *IEEE Standard for Terminology and Test Methods for Analog-to-Digital Converters* (SINAD, ENOB, THD, SFDR).
- Peterson, J. (1993). *Observations and modeling of seismic background noise*. USGS Open-File Report 93-322.
- Welch, P. D. (1967). The use of fast Fourier transform for the estimation of power spectra. *IEEE Transactions on Audio and Electroacoustics*, 15(2), 70–73.
- Harris, F. J. (1978). On the use of windows for harmonic analysis with the discrete Fourier transform. *Proceedings of the IEEE*, 66(1), 51–83.
- Heinzel, G., Rüdiger, A., Schilling, R. (2002). *Spectrum and spectral density estimation by the Discrete Fourier transform (DFT), including a comprehensive list of window functions and some new flat-top windows*. Max-Planck-Institut für Gravitationsphysik.
- McNamara, D. E., Buland, R. P. (2004). Ambient noise levels in the continental United States. *Bulletin of the Seismological Society of America*, 94(4), 1517–1527.
- Holcomb, L. G. (1989). *A direct method for calculating instrument noise levels in side-by-side seismometer evaluations*. USGS Open-File Report 89-214.
- Sleeman, R., van Wettum, A., Trampert, J. (2006). Three-channel correlation analysis: a new technique to measure instrumental noise of digitizers and seismic sensors. *Bulletin of the Seismological Society of America*, 96(1), 258–271.
- Bendat, J. S., Piersol, A. G. *Random Data: Analysis and Measurement Procedures*. Wiley (cohérence, incertitudes des estimateurs spectraux).

## Annexe B — Corrections apportées à la v1

L'orthographe et la syntaxe ont été corrigées dans l'ensemble du document. Principales évolutions de fond :

| v1 | v2 |
| --- | --- |
| « ENBOB » | ENOB (*Effective Number Of Bits*), en deux variantes : relatif au sinus mesuré et ramené à la pleine échelle (§10.2) |
| « le constructeur permettra de multiplier par deux l'amplitude » | Surcharge des opérateurs (`2 * S`) ; toute opération renvoie un nouveau signal (§5.1) |
| Sens du coefficient de sensibilité non précisé | Coefficient multiplicatif en unité physique par count ; inversion à l'import StationXML (§3.2) |
| « choisir le nombre de bits avec un champ 2**24 » | Paramètre `full_scale` : PE crête-à-crête en counts, 2**24 par défaut, soit 24 bits (§7.1) |
| Formule de la dynamique donnée sans définition | PE/(2√2) explicité (RMS d'un sinus pleine échelle), calcul en counts, valeur de référence 146,26 dB pour 24 bits (§8.1) |
| `SFDR(S)`, `THD(S)` | Fonctions `sfdr`, `thd`, `sinad` en minuscules (PEP 8), alias en majuscules conservés (§3.2) |
| `s.lnm()` et `lnm(s)` | Les deux formes sont supportées : la méthode délègue à la fonction (§5.1) |
| Bande d'étude et secteur décrits séparément pour chaque analyse | Paramètres communs définis une seule fois, défauts explicités (§7) |
| « mêmes options que le SINAD » pour SFDR et THD | Algorithmes précisés : spectre du résidu (SFDR), ajustement multi-harmonique (THD), SNR ajouté (§10) |
| « temps cohérents » pour l'addition | Règles précises : recouvrement, interpolation, rééchantillonnage, unités et sensibilités (§5.1) |
| Contrainte de compatibilité web évoquée | Règles d'architecture R1 à R9 (§4) |
| `acq_mseed.py` « à améliorer si nécessaire » | Défauts identifiés (trous interpolés silencieusement, écriture en fin d'acquisition seulement, configuration codée en dur…) et améliorations précises (§13.1) |
| IA : principe général | Fichier `agent.md` généré automatiquement, `/init`, contexte, sécurité, confidentialité (§17) |
| Documentation non mentionnée | Section dédiée, livrable obligatoire (site Quarto, en anglais) : algorithmes, fonctionnement, développeur, définition de « terminé » (§18) |
| — | Ajouts : glossaire, conventions, objet `Result`, validation chiffrée, exigences non fonctionnelles, lots, points ouverts |
