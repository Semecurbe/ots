# Onthesignal Web — Cahier des charges (phase 2)

| Version | Date | Objet |
| --- | --- | --- |
| v1 | 2026-11-20 | Première rédaction : reprise graphique des fonctionnalités de la v2, éditeur Monaco, terminal, chat IA |
| v1.1 | 2026-11-20 | Terminal : terminal Python relié aux signaux de la session, à la place du shell du système (§10) |
| v1.2 | 2026-11-20 | Encart listant tous les objets, affichés d'un clic (§6.1) ; résultats propres à chaque fonction et mesure sous les graphiques (§7.5) |
| v1.3 | 2026-11-20 | Décisions sur les points ouverts (§17) : propositions, priorités et ordre des lots validés ; pas d'authentification |
| v1.4 | 2026-11-20 | Passage à NiceGUI 4 (§3.1) : versions figées des bibliothèques, navigateurs pris en charge (§14) |
| v1.5 | 2026-11-20 | Lot W8 réalisé : précisions sur le zoom à la molette (§5.1), le spectrogramme (§5.4), la comparaison (§7.6), le temps réel (§8.2) et les lots (§8.5) ; adaptations du code (annexe B) |
| v1.6 | 2026-11-20 | Navigation dans les graphiques comme dans matplotlib (§5.1) : vue complète, vues précédente et suivante, modes zoom et déplacement ; marge transmise autour de la fenêtre d'un tracé temporel (§5.2) |
| v1.7 | 2026-11-20 | Zoom par rectangle sur les deux axes (§5.1) ; superposition de signaux choisis par cases à cocher dans l'encart des objets (§6.1, §6.4) ; modification des échantillons depuis le terminal (§10.2) ; application installable (PWA), fenêtre de bureau et AppImage (§3.5) |
| v1.8 | 2026-11-20 | Lot W9 réalisé : précisions sur le thème sombre (§4.8), l'aide à l'écriture de Python (§9.4), le chat (§11.2, §11.4, §11.5) et la vue `Settings` (§13) ; points P2 réalisés : niveaux ±PE/2 (§5.2), variables en tableau et en arborescence (§6.1), `plot()` (§10.3), `Ask AI about selection` (§9.6), `Regenerate` (§11.2) |

## Lecture du document

- Ce document complète le cahier des charges de la phase 1, [`onthesignal_v2.md`](onthesignal_v2.md), noté « v2 » : « v2 §9 » renvoie au §9 de ce document. Tout ce qui n'est pas redéfini ici s'applique tel quel : conventions (v2 §3), règles d'architecture R1 à R9 (v2 §4.3), algorithmes (v2 §7 à §13), documentation (v2 §18), qualité et tests (v2 §19), exigences non fonctionnelles (v2 §20).
- Les calculs ne sont pas redécrits : l'interface web appelle les mêmes fonctions que la console.
- **P1** : indispensable à la première version web utilisable · **P2** : important · **P3** : confort ou évolution. Priorités validées le 2026-11-20 (§17).
- Les noms en `police fixe` sont les noms cibles de l'implémentation. Comme la console, l'interface web est entièrement en anglais (v2 §3.2) : libellés, menus, messages, aide. Seul le présent document est rédigé en français.
- Les nouvelles règles prolongent la numérotation de la v2 (R10 à R17). Les cas de validation propres au web sont notés W-01, W-02… et les lots de développement W0, W1…

## Sommaire

1. Objet et contexte
2. Périmètre et phasage
3. Architecture et règles de conception
4. Organisation de l'interface
5. Graphiques µPlot
6. Signaux
7. Analyses et résultats
8. Acquisition, temps réel, rapports, scripts et lots
9. Éditeur de texte Monaco
10. Terminal
11. Chat IA
12. Sécurité
13. Configuration
14. Exigences non fonctionnelles
15. Documentation, tests et validation
16. Organisation du code et lots de développement
17. Décisions sur les points ouverts

- Annexe A — Correspondance console → interface web
- Annexe B — Adaptations du code existant
- Annexe C — Références

---

## 1. Objet et contexte

Onthesignal Web est l'interface graphique annoncée pour la phase 2 (v2 §1). Elle s'utilise dans un navigateur et poursuit trois objectifs :

1. **reprendre graphiquement l'ensemble des fonctionnalités de la console** : chargement et gestion des signaux, analyses de bruit, comparaison au NLNM, analyses sur sinus, mesures, cohérence, spectrogramme, acquisition et temps réel SeedLink, rapports, scripts et lots, assistant IA, configuration ;
2. **offrir un environnement de travail complet** autour de ces analyses : un éditeur de texte Monaco (scripts, `context.md`, configuration, rapports), un terminal Python dans lequel les signaux de la session sont des variables, et un chat avec l'assistant IA ;
3. **rendre les résultats explorables** : graphiques interactifs µPlot (zoom, curseur, lecture des valeurs), comparaison de résultats, sélection d'une fenêtre temporelle à la souris.

Principe directeur : **l'interface web est une nouvelle couche d'interface, pas un nouveau logiciel.** Elle s'appuie sur le cœur de calcul, le registre des commandes, la session, les rapports, les scripts et l'assistant existants (v2 §4.2). Toute fonctionnalité de la console est disponible dans le navigateur, et inversement (règle de parité R17).

Usages visés :

- sur le poste du banc de mesure, avec un navigateur local (`http://127.0.0.1:8080`) ;
- à distance, depuis un portable, vers le poste du banc ou un serveur de calcul, par un tunnel SSH (§12.3) ;
- avec un modèle d'IA local accessible sur le réseau (Ollama sur un GB10 avec Qwen3.8, voir `ollama.md`) ou en ligne (Claude).

Une instance du serveur sert **un utilisateur, un projet et une session**. Ce n'est pas une application multi-utilisateur.

## 2. Périmètre et phasage

### 2.1 Fonctionnalités

| Domaine | Contenu | Priorité | Section |
| --- | --- | --- | --- |
| Socle | lancement `onthesignal web`, sécurité (écoute locale, contrôle de l'origine), disposition de type environnement de développement, palette de commandes, barre d'état, tâches de fond | P1 | 3, 4, 12 |
| Graphiques | composant µPlot générique alimenté par une description de figure neutre (R11), décimation min/max | P1 | 5 |
| Encart des objets | liste permanente de tous les objets de la session (signaux, résultats, figures, variables du terminal Python) ; un clic affiche l'objet | P1 | 6.1 |
| Signaux | chargement (fichiers du serveur, téléversement, glisser-déposer, assistant pour les fichiers texte), tracé temporel avec propriétés et statistiques en dessous, sélection, opérations, signaux de test, export | P1 | 6 |
| Analyses | lanceur générique alimenté par le registre, formulaires générés (R3), onglets de résultats | P1 | 7 |
| Résultats sous les graphiques | sous chaque graphique, résultats propres à la fonction ou à la mesure : avertissements, chiffres clés, détail, tableaux | P1 | 7.5 |
| Bruit, NLNM, sinus | `noise`, `noise_fft`, `noise_dsp`, `lnm`, `sinefit`, `sinad`, `sfdr`, `thd`, `dynamic` | P1 | 7.4 |
| Mesures, cohérence, spectrogramme | `frequency`, `period`, `delay50`, `coherence`, `spectrogram` | P2 | 7.4 |
| Comparaison | superposition de résultats de même nature | P2 | 7.6 |
| Rapports | panier de résultats, génération, rendu Quarto, aperçu, téléchargement | P1 | 8.3 |
| Acquisition | SeedLink : choix des voies, progression par voie, arrêt propre | P1 | 8.1 |
| Temps réel | tableau de bord : statistiques glissantes, trace, FFT, DSP | P2 | 8.2 |
| Scripts | liste, création à partir du modèle, édition, exécution avec formulaire | P1 | 8.4 |
| Lots | traitement par lots avec suivi et tableau de résultats | P2 | 8.5 |
| Éditeur | Monaco : explorateur, onglets, enregistrement, vérification syntaxique, exécution | P1 | 9 |
| Éditeur avancé | complétion Python tenant compte de la session, diagnostics ruff, propositions de l'IA en vue différentielle | P2 | 9.4, 9.6 |
| Terminal Python | terminal relié à la session : signaux sous forme de variables, fonctions d'onthesignal, commandes `/`, complétion, historique, interruption | P1 | 10 |
| Chat IA | conversation, appels d'outils visibles, confirmations, choix du modèle, `/init`, contexte | P1 | 11 |
| Chat avancé | réponse affichée au fil de l'eau, historique, profils de modèles, mentions `@`, consommation du contexte | P2 | 11 |
| Configuration | vue des réglages avec leur origine, édition | P2 | 13 |
| Documentation | manuel utilisateur de l'interface web, documentation développeur (v2 §18) | **P1 — obligatoire** | 15.1 |

### 2.2 Hors périmètre

- Plusieurs utilisateurs simultanés avec comptes et droits distincts ; exposition sur Internet.
- Édition collaborative en temps réel.
- Affichage sur téléphone (tablette en paysage : P3).
- Analyses propres au web : toute nouvelle analyse est d'abord ajoutée au cœur (procédure v2 §18.3) et apparaît alors automatiquement dans le web (R17).
- Terminal du système (shell) : le terminal de l'interface est un terminal Python (§10) ; les commandes du système se tapent dans le terminal habituel du poste.

### 2.3 Évolutions envisagées (pour mémoire)

- Application de bureau (fenêtre native, NiceGUI `native=True`).
- Navigation dans une archive SDS et chargement par voie et par fenêtre temporelle.
- Sauvegarde et restauration de la session (v2 §5.3) ; plusieurs projets ou sessions par instance.
- Export de l'historique de la session sous forme de script reproductible.
- Intégration de git dans l'interface (état, différences).
- Terminal du système (shell) en option, désactivé par défaut.
- Authentification (jeton ou mot de passe), si un usage partagé sur le réseau devient nécessaire.

## 3. Architecture et règles de conception

### 3.1 Technologies

| Usage | Choix | Statut |
| --- | --- | --- |
| Interface web | NiceGUI 4.x (≥ 4.0) | Imposé |
| Graphiques interactifs | µPlot 1.6 (≥ 1.6.32) | Imposé |
| Éditeur de texte | Monaco Editor (≥ 0.56) | Imposé |
| Terminal Python | moteur de la console de la v2 (prompt_toolkit) sur un pseudo-terminal, affiché par xterm.js 6 (élément `ui.xterm` de NiceGUI) | Recommandé |
| Complétion Python (éditeur et terminal) | Jedi (`jedi.Interpreter`, qui voit les objets de la session) | Recommandé |
| Diagnostics Python | ruff | Recommandé |
| Figures des rapports | matplotlib (rendu côté serveur, inchangé) | Imposé |
| Rapports | Quarto | Imposé |

- Versions vérifiées en novembre 2026 et figées au lot W0 : NiceGUI 4.0 (passage de la 3.19 à la 4.0 le 2026-11-20), qui apporte Quasar 2.35, Vue 3.5 et xterm.js 6 ; µPlot 1.6.32 et Monaco 0.56.0, embarqués (`web/static/vendor/VENDOR.md`).
- NiceGUI 4 demande Python ≥ 3.11, version déjà imposée par la v2 (v2 §4.1), et des navigateurs récents (§14). Ses changements de comportement (exception `CancelledError` de `run.io_bound`, identifiants `ng-…` des éléments, `ui.tab` obligatoirement dans `ui.tabs`, fond de xterm.js 6…) sont décrits dans la documentation développeur (`docs/developer/web-phase.qmd`).
- Toutes les bibliothèques JavaScript sont **embarquées dans le paquet** (versions figées, licences jointes) et servies par l'application : aucun CDN, fonctionnement hors ligne (v2 §20).
- Monaco est chargé à la première ouverture d'un éditeur, pas au démarrage.
- `pip install -e ".[web]"` installe NiceGUI 4 et Jedi (`web = ["nicegui>=4.0,<5", "jedi>=0.19"]` dans `pyproject.toml`) ; ruff y sera ajouté avec les diagnostics de l'éditeur (P2, lot W9).

### 3.2 Couches logicielles

```text
Interfaces   cli (console)          web (NiceGUI)
                                    ├── cadre : disposition, palette, barre d'état, panneaux
                                    ├── vues : signaux, analyses, résultats, acquisition…
                                    ├── composants : µPlot, Monaco, terminal Python, chat
                                    └── services web : sécurité, tâches, PTY, fichiers
Services     session observable · registre · rapports · IA · scripts · hôte utilisateur
Rendu        description de figure neutre (FigureSpec) · figures matplotlib
Cœur         core · io · processing · analysis · seedlink
```

### 3.3 Règles de conception (obligatoires)

Les règles R1 à R9 (v2 §4.3) restent applicables. Les règles suivantes s'y ajoutent.

- **R10 — Aucun calcul dans la couche web.** Le web appelle le registre (`run` et les fonctions de l'API), les scripts, les rapports et l'assistant. Il ne contient aucun traitement du signal. Les seuls calculs admis sont ceux de la présentation (décimation, statistiques de la fenêtre affichée) ; ils sont fournis par `processing` et partagés avec la console.
- **R11 — Description de figure neutre.** Chaque type de résultat dispose d'une fonction de mise en page `layout(result) -> FigureSpec`, qui décrit la figure indépendamment du moteur de rendu (panneaux, axes, séries, repères, zones, annotations, §5.3) ainsi que le panneau de résultats affiché sous la figure (§7.5). Le composant µPlot est générique : il affiche n'importe quelle `FigureSpec`. Les règles graphiques de la v2 (par exemple v2 §10.2 : conditions de calcul au-dessus du spectre, traits rouges aux raies secteur supprimées, axe logarithmique) sont exprimées une seule fois, dans ces mises en page, et vérifiées par des tests. Un résultat sans mise en page dédiée (script utilisateur, nouvelle analyse) reçoit une **mise en page générique** construite à partir de ses `curves`.
- **R12 — Boucle d'événements jamais bloquée.** NiceGUI repose sur asyncio : toute opération de plus de 50 ms (chargement, analyse, rapport, appel à l'IA, lot) s'exécute dans un thread (`run.io_bound`) ou un processus. L'interface n'est modifiée que depuis la boucle d'événements : les threads publient leur état dans des structures protégées, que l'interface lit (minuterie ou tâche asynchrone).
- **R13 — Session observable.** Toute modification de la session émet un événement : signal ajouté, supprimé, renommé ou modifié (unité, sensibilité, pleine échelle, titre), résultat ajouté ou supprimé, variable du terminal Python créée, modifiée ou supprimée, figure créée, historique complété, configuration modifiée. Les vues s'y abonnent : une modification faite depuis le terminal Python, l'IA, un script ou un autre onglet du navigateur apparaît immédiatement partout. Les accès concurrents à la session sont protégés.
- **R14 — Dialogue avec l'utilisateur abstrait.** L'assistant, les scripts et les commandes ne dépendent plus de la console. Ils dialoguent avec l'utilisateur par une interface `UserHost` (messages, confirmation, formulaire, affichage d'un résultat), implémentée par la console (de façon synchrone) et par le web (boîtes de dialogue asynchrones) (annexe B).
- **R15 — Sécurité par défaut.** Pas d'authentification (§17, point 6) ; en contrepartie, écoute sur la seule boucle locale par défaut, contrôle de l'origine des connexions et accès aux fichiers limité au projet (§12).
- **R16 — Volume transmis au navigateur maîtrisé.** Le navigateur reçoit des données décimées (par défaut deux points par pixel de largeur et par série, en enveloppe min/max), jamais un signal complet. La pleine résolution n'est transmise que sur demande explicite d'export. La décimation conserve les extremums : un pic isolé d'un seul échantillon ou une raie spectrale étroite restent visibles.
- **R17 — Parité avec la console.** Toute commande du registre est accessible dans le web par des mécanismes génériques (palette, lanceur, formulaire généré, onglet de résultat), sans code propre à la commande. Les vues spécifiques (acquisition, temps réel, rapports, éditeur, terminal, chat) n'existent que pour offrir une ergonomie plus riche. L'annexe A donne la correspondance complète.

### 3.4 Lancement et modèle d'exécution

```text
onthesignal web [files…] [--host 127.0.0.1] [--port 8080] [--project DIR] [--no-browser]
```

- La commande démarre le serveur, affiche son adresse (`http://127.0.0.1:8080`) et ouvre le navigateur. Les fichiers passés en argument sont chargés dans la session.
- Le répertoire du projet (défaut : répertoire courant) contient `onthesignal.toml`, `context.md`, `scripts/`, `reports/` et `.onthesignal/` (v2 §21.1).
- Une instance = un utilisateur = un projet = une session. Plusieurs onglets du navigateur peuvent être ouverts sur la même instance : ils partagent la session et restent synchronisés (R13). La disposition (onglets ouverts, panneaux) est propre à chaque navigateur.
- Recharger la page ou subir une coupure réseau ne fait rien perdre : la session, les tâches de fond (acquisition, temps réel, rendu de rapport, lot) et le terminal Python vivent dans le serveur, et l'interface se reconnecte automatiquement.
- Dans le serveur, matplotlib utilise un moteur sans fenêtre (`Agg`) : `S.show()` et les analyses affichent leur résultat dans un onglet du navigateur (par `session.display_handler`), jamais dans une fenêtre du serveur.
- Arrêt : Ctrl+C dans le terminal de lancement, ou commande `Shut down server` (avec confirmation). L'arrêt termine proprement l'acquisition en cours (données enregistrées), ferme le terminal Python et les connexions SeedLink.

### 3.5 Application installable, fenêtre de bureau, AppImage

- L'interface est une application web progressive (PWA) : manifeste, icônes et service worker permettent de l'installer depuis Chrome, Edge ou Safari, avec sa propre fenêtre et son icône. Le service worker ne met pas l'interface en cache (elle est pilotée en temps réel par le serveur) : si le serveur ne répond pas, la fenêtre explique comment le démarrer. Les navigateurs n'installent une application que depuis `127.0.0.1`, `localhost` (tunnel SSH compris) ou HTTPS.
- `onthesignal desktop` affiche l'interface dans une fenêtre dotée de son propre moteur web (Chromium de Qt WebEngine, dépendance `[desktop]`), à la manière d'une application Electron : il démarre le serveur sur un port libre de la boucle locale et l'arrête à la fermeture de la fenêtre. Cette réalisation remplace la fenêtre native par pywebview envisagée en P3 (§2.3, §17 point 12).
- Une AppImage, construite par `packaging/appimage/build_appimage.py`, contient Python, onthesignal et Qt WebEngine : elle s'exécute sans installation et ouvre la fenêtre de bureau (la console et les autres commandes restent accessibles). Quarto n'y est pas inclus.

## 4. Organisation de l'interface

### 4.1 Disposition générale

Disposition inspirée des environnements de développement (VS Code, JupyterLab) : barre d'activité à gauche ; colonne latérale avec l'encart des objets (§6.1) ; zone de travail à onglets, où chaque graphique est suivi de son panneau de résultats (§7.5) ; chat à droite ; panneau inférieur (terminal Python, sorties) ; barre d'état.

```text
┌─────────────────────────────────────────────────────────────────────────────────────────────────┐
│ onthesignal · ~/bench3     [ / Search commands, objects, files ]    Qwen3.8 · GB10              │
├─────┬────────────────────────┬────────────────────────────────────────┬─────────────────────────┤
│ Fil │ OBJECTS       [filter] │ S1 x | R1 noise_dsp S1 x | R2 lnm S3 x │ AI CHAT                 │
│ Ana │ SIGNALS (4)            │                                        │ > is S3 below the NLNM? │
│ Acq │   S1  RD.SN270.00.FHZ  │     µPlot figure: zoom, cursor, legend │   -> lnm(S3)       done │
│ RT  │   S2  RD.SN270.00.FHN  │                                        │ S3 is below the NLNM    │
│ Rep │   S3  RD.SN270.00.HHZ  │                                        │ from 1 to 30 s, but…    │
│ Scr │   S4  = S1 - S2        ├────────────────────────────────────────┤                         │
│ Set │ RESULTS (2)            │ RESULTS · noise_dsp · S1               │                         │
│ ?   │ > R1  noise_dsp S1     │ RMS 2.43 µV | DR 135.3 dB | ENOB 22.2  │                         │
│     │   R2  lnm S3           │ Mean          12.31 counts  (29.35 µV) │                         │
│     │ FIGURES (1)            │ Peak-to-peak   9.12 counts  (21.74 µV) │                         │
│     │   Figure 1             │ ENBW 99.8 Hz · 50, 100 Hz removed      │                         │
│     │ VARIABLES (1)          │ Parameters ▸   Traceability ▸          │                         │
│     │   f   ndarray (8193)   │                                        │ [ @ / Message…      ]   │
│     ├────────────────────────┴────────────────────────────────────────┴─────────────────────────┤
│     │ PYTHON   OUTPUT   PROBLEMS   JOBS   HISTORY                                               │
│     │ ots> S4 = S1 - S2              # S4 appears in OBJECTS                                    │
├─────┴───────────────────────────────────────────────────────────────────────────────────────────┤
│ 4 signals · 2 results · noise_dsp S1 done (0.8 s) · context 9.6k / 262k · 14:02 UTC             │
└─────────────────────────────────────────────────────────────────────────────────────────────────┘
```

- Tous les panneaux sont redimensionnables et repliables ; la disposition est mémorisée par le navigateur.
- Écran de référence 1920×1080 ; l'interface reste utilisable à partir de 1366×768, vue latérale, chat et panneau inférieur repliés.

### 4.2 Colonne latérale et barre d'activité

La colonne de gauche affiche en permanence l'encart `Objects` (§6.1). La barre d'activité ouvre, sous l'encart, l'une des vues suivantes ; l'encart et la vue se partagent la hauteur, et chacun peut être replié.

| Vue | Contenu | Priorité |
| --- | --- | --- |
| `Files` | explorateur du projet (§9.2) | P1 |
| `Analyses` | registre par catégorie (bruit, sinus, mesures, spectral), scripts, signaux de test (§7.1) | P1 |
| `Acquisition` | acquisition SeedLink (§8.1) | P1 |
| `Real time` | temps réel SeedLink (§8.2) | P2 |
| `Reports` | rapports et panier du rapport (§8.3) | P1 |
| `Scripts` | scripts et lots (§8.4, §8.5) | P1 |
| `Settings` | configuration (§13) | P2 |
| `Help` | aide du registre (`/help`), documentation (§15.1), raccourcis clavier (§4.7) | P1 |

### 4.3 Zone de travail

- Onglets typés : tracé temporel d'un ou plusieurs signaux, résultat d'analyse, fichier ouvert dans l'éditeur, aperçu de rapport, tableau de bord temps réel, progression d'acquisition, aide.
- Les onglets se déplacent et se ferment ; ils indiquent une modification non enregistrée (fichiers) ou une activité (tâche en cours). Partage de la zone en deux, côte à côte : P2.
- Un clic sur un objet de l'encart l'affiche (§6.1). Un résultat produit par le terminal Python, l'IA ou un script s'ouvre dans un onglet sans retirer le focus du champ en cours de saisie.

### 4.4 Palette de commandes

Transposition du menu `/` de la console (v2 §15.2, ergonomie inspirée d'opencode) :

- ouverture par `/` (hors d'un champ de saisie) ou Ctrl+K ; Ctrl+P ouvre directement un fichier ou un signal ;
- liste filtrée au fil de la frappe (recherche approximative) : commandes du registre et de la console, avec leur description courte, signaux, résultats, fichiers, actions de l'interface (`Toggle dark mode`, `Focus Python terminal`, `Shut down server`…) ;
- saisie directe d'une commande complète, comme dans la console : `/noise S1 fmax=50 remove_mains=true` lance l'analyse, `/noise S1` ouvre le formulaire ;
- contenu construit à partir du registre (R8) : une nouvelle analyse y apparaît sans modification du web.

### 4.5 Barre d'état

Nombre de signaux et de résultats ; dernière action et sa durée ; tâches en cours (acquisition, temps réel, rendu, lot) avec leur avancement ; profil d'IA actif, local ou en ligne, et contexte utilisé ; répertoire du projet ; heure UTC ; état de la connexion au serveur.

### 4.6 Panneau inférieur

| Onglet | Contenu |
| --- | --- |
| `Python` | terminal Python relié à la session (§10) |
| `Output` | journaux des tâches (rendu Quarto, acquisition, lots), filtrables par tâche |
| `Problems` | avertissements des résultats et erreurs, avec lien vers l'onglet concerné ; trace complète si le réglage `Show tracebacks` est actif (équivalent de `/debug on`) |
| `Jobs` | tâches de fond : état, avancement, durée, annulation |
| `History` | historique de la session (traçabilité R9), copiable |

### 4.7 Raccourcis clavier

| Raccourci | Action |
| --- | --- |
| `/`, Ctrl+K | palette de commandes |
| Ctrl+P | ouvrir un fichier ou un signal |
| Ctrl+Entrée | lancer l'analyse du formulaire ouvert |
| Ctrl+S | enregistrer le fichier |
| F5 | exécuter le script ouvert |
| Shift+Entrée | exécuter la sélection ou la cellule `# %%` dans le terminal Python |
| Ctrl+` | afficher ou masquer le terminal Python |
| Ctrl+Shift+I | afficher ou masquer le chat |
| Ctrl+W | fermer l'onglet |
| Échap | fermer la palette ou la boîte de dialogue |

Lorsqu'ils ont le focus, l'éditeur et le terminal gardent leurs propres raccourcis. La liste complète est affichée dans `Help`.

### 4.8 Thème et style

- Thème clair (P1) et thème sombre (P2), qui suivent par défaut le réglage du système et se commutent à la demande.
- Les couleurs des graphiques reprennent celles de `plot/style.py` (séries, encre, grille, rouge des raies supprimées) : les figures du web et celles des rapports se ressemblent. Le thème sombre utilise une palette dédiée, validée sur fond sombre (contraste, daltonisme), et non une inversion automatique.
- Les textes utilisent les couleurs d'encre, jamais la couleur d'une série.
- Réalisation : la palette sombre reprend les huit teintes de la palette claire, avec des pas propres au fond sombre (`#1a1a19`), validés par le calcul (contraste ≥ 3:1, séparation pour les daltonismes) ; sur fond sombre, la rampe séquentielle du spectrogramme va du sombre au clair. Le thème se choisit dans l'en-tête (système, clair, sombre) ; `[web] theme` donne la valeur initiale.

### 4.9 Erreurs et notifications

- Une erreur n'interrompt jamais l'interface : message clair en anglais (notification) et entrée dans `Problems`. Les erreurs de paramètres sont signalées sur le champ concerné.
- La fin d'une tâche longue est notifiée dans l'interface ; notification du navigateur : P3.

## 5. Graphiques µPlot

### 5.1 Composant générique

Un composant unique affiche une `FigureSpec` (§5.3) :

- panneaux superposés partageant l'axe des abscisses (zoom et curseur synchronisés), avec des hauteurs relatives ;
- axes linéaires ou logarithmiques, libellés avec leurs unités ;
- légende toujours présente dès deux séries, avec la valeur sous le curseur ; un clic sur une entrée masque ou affiche la série ;
- curseur en croix avec lecture des coordonnées dans les unités des axes ;
- zoom par sélection rectangulaire, retour à la vue complète par double-clic ; zoom à la molette (P2) avec la touche Ctrl, autour du curseur : la molette seule fait défiler la zone de travail, qui contient aussi les résultats ;
- barre d'outils de navigation sur chaque graphique, comme dans les fenêtres matplotlib : vue complète, vue précédente et vue suivante (chaque zoom ou déplacement peut être annulé puis rétabli), mode « zoom » (mode par défaut : glisser un rectangle zoome sur les deux axes, comme *Zoom to rectangle* de matplotlib ; un glisser presque horizontal ne zoome que les abscisses) et mode « déplacement » (glisser le graphique ; l'ordonnée fixée par un rectangle suit le mouvement vertical) ; dans les deux modes, le bouton du milieu et Maj + molette déplacent la vue ;
- repères verticaux (raies secteur supprimées en tirets rouges, harmoniques H2, H3…, raie parasite du SFDR, fondamentale), lignes horizontales (0 dB), zones (bande d'étude, trous), remplissages (domaine sous le NLNM) ;
- annotations : conditions de calcul au-dessus du panneau concerné ; les résultats sont affichés sous le graphique (§7.5), **jamais en surimpression des données** (en phase 1, l'encadré matplotlib masquait la raie à 50 Hz) ;
- styles des séries (épaisseur, tirets, transparence) et couleurs désignées par leur rôle (`series:0`, `ink2`, `removed`…), résolues selon le thème.

### 5.2 Tracé temporel

- Un ou plusieurs signaux, superposés ou empilés en panneaux à axe des temps commun.
- Abscisse en secondes depuis un instant de référence UTC indiqué sous l'axe ; la lecture du curseur donne le temps UTC absolu. Cela évite la perte de précision des temps absolus représentés en virgule flottante dans le navigateur.
- Bascule entre unités physiques et counts.
- L'enveloppe min/max (R16) est recalculée côté serveur pour la fenêtre visible à chaque zoom, la requête étant différée de 150 ms. Lorsque la fenêtre compte moins d'échantillons que de points demandés, les échantillons réels sont affichés. Le serveur transmet aussi une largeur de fenêtre de chaque côté, à la même résolution, pour que le déplacement soit immédiat ; les statistiques restent celles de la fenêtre visible.
- Statistiques de la fenêtre visible, affichées sous le graphique et mises à jour à chaque zoom (§6.2).
- Trous matérialisés par des zones grisées. P2 : niveaux ±PE/2 affichés lorsque le signal s'en approche.
- Sélection d'une fenêtre temporelle (Shift + glisser) : `Analyze selection…` (lanceur prérempli avec `t_start` et `t_end`), `Slice to new signal`, `Zoom to selection`.

### 5.3 Description de figure (`FigureSpec`)

Structure sérialisable en JSON, produite côté serveur (R11). Les données des courbes sont transmises séparément, décimées (R16).

| Élément | Contenu |
| --- | --- |
| `title` | titre du résultat, avec le libellé du signal |
| `panels[]` | `id`, hauteur relative, axes `x` et `y` (libellé, unité, échelle `linear` ou `log`, bornes), `series[]`, `markers[]`, `hlines[]`, `bands[]`, `fills[]`, `conditions` (lignes de texte) |
| `series[]` | clé de la courbe dans `Result.curves`, libellé, rôle (`data`, `smoothed`, `model`, `fit`, `reference`), style |
| `markers[]` | abscisse, libellé, nature (`removed_mains`, `harmonic`, `spur`, `fundamental`, `event`) |
| `results` | panneau de résultats sous la figure (§7.5) : `headline[]` (clés des chiffres clés), `groups[]` (titre et clés du détail), `tables[]` (tableaux issus de `Result.extra`, par exemple les harmoniques) |
| `sync_x` | axes des abscisses synchronisés entre les panneaux |

Exemple pour `lnm` (v2 §9) :

```json
{
  "title": "PSD vs NLNM — S3 · velocity · 3600 s",
  "sync_x": true,
  "panels": [
    {
      "id": "psd", "height": 2,
      "x": {"label": "Frequency", "unit": "Hz", "scale": "log"},
      "y": {"label": "PSD", "unit": "dB re 1 (m/s)²/Hz"},
      "series": [
        {"curve": "psd", "label": "PSD (raw)", "role": "data", "style": {"width": 0.6, "alpha": 0.35}},
        {"curve": "psd_smooth", "label": "PSD (1/8 octave)", "role": "smoothed"},
        {"curve": "nlnm", "label": "NLNM", "role": "model"}
      ]
    },
    {
      "id": "diff", "height": 1,
      "x": {"label": "Frequency", "unit": "Hz", "scale": "log"},
      "y": {"label": "PSD − NLNM", "unit": "dB"},
      "series": [{"curve": "diff", "label": "PSD − NLNM", "role": "data"}],
      "hlines": [{"y": 0}],
      "fills": [{"curve": "diff", "below": 0, "label": "below NLNM"}]
    }
  ],
  "results": {
    "headline": ["diff_max", "freq_max", "below_nlnm"],
    "groups": [
      {"title": "PSD − NLNM", "keys": ["quantity", "diff_min", "diff_mean", "period_max", "range"]},
      {"title": "Welch", "keys": ["nperseg", "n_averages"]}
    ]
  }
}
```

Mise en page générique : un panneau par grandeur et unité des ordonnées, regroupant toutes les courbes du résultat ; échelle des abscisses reprise de `Curve.xscale` ; toutes les valeurs du résultat dans le détail du panneau de résultats.

### 5.4 Spectrogramme (P2)

µPlot ne trace pas de cartes de couleurs. L'image est donc calculée côté serveur (palette et bornes de couleur de v2 §12.2) et dessinée dans la zone de tracé par un greffon µPlot, qui conserve les axes, le zoom et la lecture du curseur (temps, fréquence, niveau en dB). Une barre de couleur l'accompagne ; la trace temporelle peut être affichée au-dessus, avec l'axe des temps partagé.

Réalisation : le serveur envoie la grille des niveaux, réduite à 400 × 800 cellules au plus en conservant le maximum des cellules regroupées (une raie étroite reste visible, R16) et quantifiée sur 16 bits ; le navigateur la colore et y lit le niveau sous le curseur. Sur un axe des fréquences logarithmique, les lignes de la grille sont régulières en log f.

### 5.5 Export

- `PNG` : image du graphique tel qu'il est affiché (résolution doublée), avec titre et légende.
- `Publication figure` : figure matplotlib rendue côté serveur (PNG, SVG, PDF), identique à celle des rapports.
- `CSV` : courbes du résultat en pleine résolution.

### 5.6 Performances

- Affichage d'un résultat spectral (jusqu'à 10⁶ points par courbe avant décimation) en moins de 300 ms après réception.
- Tracé temporel d'un signal de 10⁷ échantillons (v2 §20) affiché en moins de 2 s ; mise à jour après un zoom en moins de 500 ms.
- Rafraîchissement de six voies temps réel chaque seconde, sans saccade ni croissance de la mémoire du navigateur.

## 6. Signaux

### 6.1 Encart des objets (P1)

L'encart `Objects`, toujours visible en haut de la colonne de gauche, liste **tous les objets de la session**. Un clic sur un objet l'affiche dans la zone de travail.

| Groupe | Objets | Ligne affichée | Effet du clic |
| --- | --- | --- | --- |
| `Signals` | signaux de la session (`S1`, `S2`…) | nom, NSLC ou titre, fréquence d'échantillonnage, durée, unité | tracé temporel, avec propriétés et statistiques sous le graphique (§6.2) |
| `Results` | résultats des analyses et des scripts (`R1`, `R2`…) | nom, analyse, signal, chiffre clé (par exemple `RMS 2.43 µV`) | onglet du résultat : graphique et résultats en dessous (§7.5) |
| `Figures` | figures matplotlib créées par le terminal Python ou par un script | numéro, titre | onglet `Figure` |
| `Variables` | autres variables du terminal Python : nombres, chaînes, tableaux numpy, listes, dictionnaires | nom, type, taille ou forme, aperçu de la valeur | nombre ou chaîne : valeur ; tableau à une dimension : graphique µPlot et statistiques en dessous ; P2 : tableau à deux dimensions (grille), liste et dictionnaire (arborescence) |

- Clic : l'objet s'affiche, ou son onglet revient au premier plan s'il est déjà ouvert ; l'objet affiché est surligné dans l'encart.
- Ctrl+clic : sélection multiple. Plusieurs signaux : `Plot together` (§6.4) ; plusieurs résultats de même nature : `Compare` (§7.6, P2).
- Double-clic : renommage. Survol : résumé de l'objet (pour un signal, l'essentiel de `S.print()` ; pour un résultat, ses chiffres clés).
- Menu contextuel : `Show`, `Info`, `Rename`, `Copy name`, `Analyze…` (signaux), `Add to report` (résultats), `Export…`, `Send to AI`, `Delete` (avec confirmation ; équivaut à `del` dans le terminal Python).
- Glisser-déposer : sur un tracé, ajoute le signal au tracé ; dans le chat, joint l'objet au message ; dans le terminal Python, insère son nom.
- Champ de filtre (nom, type, analyse, signal), groupes repliables, tri par nom ou par date de création. Bouton `+` : `Load…`, `Upload…`, `New test signal`, `New signal from expression`.
- Mise à jour immédiate (R13) : un objet créé depuis le terminal Python, un formulaire, l'IA, un script ou une acquisition apparaît aussitôt ; un objet supprimé disparaît.
- Nommage : chaque résultat reçoit un nom de session stable (`R1`, `R2`…), comme les signaux, utilisable dans le terminal Python (`R3["rms"]`). Une variable du terminal qui désigne un résultat (`r = noise(S1)`) est indiquée comme alias : `R3 · r`.
- Les fonctions, les modules et les noms qui commencent par `_` ne sont pas listés.

### 6.2 Affichage d'un signal (P1)

Un clic sur un signal ouvre son onglet : le tracé temporel (§5.2) en haut, et en dessous le panneau du signal.

- **Statistiques de la fenêtre visible**, mises à jour à chaque zoom : moyenne, écart-type, C-C, minimum, maximum (en counts et en unité physique), nombre d'échantillons, début et fin de la fenêtre (UTC).
- **Propriétés**, équivalent de `S.print()` (v2 §5.1) : tous les attributs, trous, historique, métadonnées.
- Champs modifiables : nom, titre, codes NSLC, unité (liste des unités reconnues, v2 §3.2), sensibilité, pleine échelle, métadonnées. Chaque modification passe par l'API, est tracée dans `history` et met à jour toutes les vues (R13).
- Aide à la saisie de la sensibilité : expression acceptée (`40 / 2**24`, `1 / (1500 * 419430)`), avec rappel de la convention `physical = counts × sensitivity` (v2 §3.2).

### 6.3 Chargement (P1)

- **Fichiers du serveur** : depuis l'explorateur (`Load as signal`), la palette, le bouton `+` de l'encart ou `Open…` (sélecteur limité aux racines configurées, motifs `*.mseed` acceptés). C'est le cas d'usage principal : les données se trouvent sur le poste du banc.
- **Téléversement** depuis l'ordinateur du navigateur : bouton `Upload` ou glisser-déposer dans la fenêtre. Les fichiers sont enregistrés dans le dossier `data/uploads/` du projet, puis chargés.
- Les options de `load` (v2 §6.1) sont proposées dans un formulaire généré : `select`, `starttime`, `endtime`, `gaps`, `sensitivity`, `unit`, `full_scale`, `name`, `title`.
- **Fichiers texte** (v2 §6.2) : assistant avec aperçu des 20 premières lignes, séparateur de colonnes et séparateur décimal détectés et modifiables, nombre de voies, colonne de temps, fréquence d'échantillonnage, format du temps. Les erreurs de lecture (nombre de colonnes, pas de temps irrégulier) sont montrées sur l'aperçu.
- Liste des fichiers récents.

### 6.4 Tracé de plusieurs signaux (P1)

`Plot together` (sélection multiple dans l'encart) ou le glisser-déposer d'un signal sur un tracé affichent plusieurs signaux ensemble, superposés ou empilés (§5.2). Le panneau sous le graphique donne alors les statistiques de la fenêtre visible pour chaque signal, une colonne par signal.

Réalisation : chaque signal et chaque résultat de l'encart a une case à cocher ; dès deux signaux cochés, les boutons `Overlay` (un seul panneau) et `Stack` (un panneau par signal) les affichent. Au-dessus d'un tracé, `Add signal` ajoute un signal et une étiquette par signal permet de le retirer. Des signaux d'unités différentes sont superposés avec un avertissement (les comparer en counts, ou les empiler).

### 6.5 Opérations (P1)

- `Copy` ; `Slice`, à partir d'une sélection du tracé ou par saisie de `t_start` et `t_end`.
- Opérations arithmétiques (v2 §5.1) : boîte de dialogue `New signal from expression` (`2 * S1`, `S1 - S2`, `S1 + S2`, choix de la méthode d'interpolation). Les avertissements d'interpolation et de rééchantillonnage sont affichés. Les mêmes opérations sont disponibles dans le terminal Python (§10).
- Signaux de test `make_sine` et `make_noise` (v2 §5.1) : `New test signal` (bouton `+` de l'encart `Objects`), avec des formulaires générés depuis leurs déclarations.
- Export (v2 §6.3) en miniSEED, texte ou CSV, enregistré dans le projet ou téléchargé.

## 7. Analyses et résultats

### 7.1 Lanceur d'analyses (P1)

- La vue `Analyses` liste les commandes du registre par catégorie, avec leur description, puis les scripts utilisateur (§8.4).
- Une analyse se lance depuis cette vue, la palette, le menu contextuel d'un signal ou une sélection du tracé. Le signal actif (onglet courant ou sélection) est proposé par défaut ; les analyses à deux signaux (`coherence`, `delay50`) demandent les deux.
- Un signal incompatible est signalé avant le lancement, avec la raison et la correction possible (par exemple `lnm` sur un signal en V : renseigner l'unité et la sensibilité de la chaîne complète, v2 §9).

### 7.2 Formulaires de paramètres (P1)

Les formulaires sont générés à partir des déclarations `Param` (R3), comme ceux de la console (v2 §15.3) :

| Déclaration | Champ |
| --- | --- |
| nombre réel ou entier | champ numérique avec son unité, qui accepte les expressions simples (`2**24`, `1e-3`) par l'évaluateur sécurisé de la console |
| booléen | interrupteur |
| liste de choix | liste déroulante |
| valeur facultative (`nullable`) | case `auto` (ou `none`) et champ |
| temps UTC | champ ISO 8601 validé, bouton `From selection` |
| signal | sélecteur de signal filtré |
| paramètre avancé | section `Advanced`, repliée par défaut |

- Chaque champ affiche sa valeur par défaut, son aide et **l'origine de sa valeur**, selon l'ordre de priorité de v2 §7.1 (appel > attribut du signal > configuration > défaut). Exemples : `full_scale` provient de `S1.full_scale`, `fmax` de `onthesignal.toml`.
- La validation est immédiate (bornes, choix) ; le bouton `Run` (Ctrl+Entrée) n'est actif que si le formulaire est valide.
- Les derniers paramètres utilisés pour chaque analyse sont repris au lancement suivant ; `Reset to defaults` rétablit les valeurs par défaut.

### 7.3 Exécution

- L'analyse s'exécute en tâche de fond (R12) ; l'onglet du résultat s'ouvre immédiatement avec un indicateur d'attente. Plusieurs analyses peuvent tourner en parallèle.
- Annulation : un calcul d'analyse en cours se termine en arrière-plan et son résultat est ignoré (les analyses durent moins de 10 s, v2 §20). L'acquisition, le temps réel, les lots, le rendu des rapports et les requêtes à l'IA sont, eux, réellement interrompus.
- Le résultat est ajouté à la session et à l'historique comme dans la console : `r = noise(S1)` dans le terminal Python et `Run` dans un formulaire produisent le même `Result`.

### 7.4 Affichage des résultats par analyse

L'onglet d'un résultat reprend l'affichage de la v2 : graphique interactif en haut, résultats en dessous (§7.5).

| Analyse | Affichage web | Réf. |
| --- | --- | --- |
| `noise` | sans graphique dans la v2 : panneau de résultats seul (§7.5) ; P2 : tracé du bruit filtré au-dessus | v2 §8.1 |
| `noise_fft` | spectre, bande d'étude grisée, raies secteur supprimées repérées, valeurs de `noise` et paramètres spectraux | v2 §8.2 |
| `noise_dsp` | DSP ou ASD avec les mêmes repères, RMS par intégration ; P2 : RMS cumulé dans un panneau séparé (pas de second axe des ordonnées) | v2 §8.3 |
| `lnm` | DSP brute et lissée, NLNM (NHNM en option) ; écart dans un second panneau synchronisé, domaine sous le NLNM mis en évidence ; bascule fréquence / période | v2 §9 |
| `sinefit` | signal et sinus ajusté (zoom sur quelques périodes), résidu | v2 §10.1 |
| `sinad` | signal et ajustement, résidu, spectre du résidu avec les conditions de calcul, traits rouges aux raies secteur supprimées, axe logarithmique | v2 §10.2 |
| `sfdr` | spectre, fondamentale, raie parasite repérée avec la cote du SFDR | v2 §10.3 |
| `thd` | spectre avec les harmoniques repérées (H2, H3…) et tableau des harmoniques | v2 §10.4 |
| `dynamic` | tableau de synthèse et contrôle de cohérence, puis un sous-onglet par figure (SINAD, SFDR, THD) | v2 §10.5 |
| `frequency`, `period` | valeurs et dispersion période par période | v2 §11.1, §11.2 |
| `delay50` | superposition des deux signaux autour d'un front, instants de passage, liste des Δt | v2 §11.3 |
| `coherence` | cohérence de 0 à 1, axe des fréquences logarithmique ; P3 : seuil de signification | v2 §12.1 |
| `spectrogram` | carte de couleurs (§5.4), trace temporelle en option | v2 §12.2 |

### 7.5 Résultats sous les graphiques (P1)

Sous chaque graphique, un panneau présente les résultats de la fonction ou de la mesure qui l'a produit. Son contenu est propre à chaque fonction et défini dans sa mise en page (R11).

Organisation du panneau, de haut en bas :

1. **Avertissements** (saturation, trous, bande réduite, SFDR limité par le plancher de bruit…), dans un bandeau avec icône et texte.
2. **Chiffres clés** : trois à cinq valeurs propres à la fonction, en grands caractères (libellé, valeur, unité ; équivalent en unité physique en dessous).
3. **Détail** : tableau `Label · Value · Physical value`, issu de `Result.rows()`, avec la mise en forme de la console (préfixes SI, chiffres significatifs).
4. **Tableaux propres à la fonction** : harmoniques, Δt de chaque front, périodes… triables et exportables.
5. **Paramètres** effectivement utilisés, avec leur origine (§7.2), et **traçabilité** (R9 : signaux, empreintes SHA-256, versions, date, durée du calcul) : sections repliées par défaut.

Contenu par fonction (libellés de l'interface) :

| Fonction | Chiffres clés | Détail | Tableaux |
| --- | --- | --- | --- |
| signal (tracé temporel) | moyenne, écart-type et C-C de la fenêtre visible | minimum, maximum, nombre d'échantillons, début et fin de la fenêtre ; propriétés (§6.2) | trous |
| `noise` | `RMS`, `Peak-to-peak`, `Dynamic range`, `Noise ENOB` | `Mean`, `Gaussian p-p (6.6 × RMS)`, `Full scale (p-p)`, `Study band`, `Noise bandwidth (ENBW)`, `Mains lines removed`, `Duration analysed`, `Samples analysed` | — |
| `noise_fft` | comme `noise` | comme `noise`, plus `Window` et `Frequency resolution` | — |
| `noise_dsp` | `RMS` et `RMS from PSD integration` côte à côte (ils doivent concorder, v2 §8.3), `Dynamic range`, `Noise ENOB` | comme `noise`, plus `Welch segment (samples)`, `Welch averages` et `Frequency resolution` | — |
| `lnm` | `Maximum PSD − NLNM`, `Frequency of the maximum difference` (ou la période, en abscisse période), `Share of the range below NLNM` | `Quantity`, `Minimum PSD − NLNM`, `Mean PSD − NLNM`, `Compared frequency range`, `Welch segment (samples)`, `Welch averages` | — |
| `sinefit` | `Frequency`, `Amplitude (peak)`, `Residual RMS` | `Phase at the record centre`, `Offset`, `Periods in the record`, `Iterations`, `Converged` | — |
| `sinad` | `SINAD`, `ENOB (relative to the sine)`, `ENOB (full scale)` | `Frequency`, `Amplitude (peak)` en counts, en unité physique et en dBFS, `Offset`, `Periods in the record`, `Full scale (p-p)`, `Noise + distortion RMS (residual)`, `THD+N`, `Study band`, `Noise bandwidth (ENBW)`, `Mains lines removed` | — |
| `sfdr` | `SFDR` (dBc), `SFDR (full scale)` (dBFS), `Largest spur frequency` et `Largest spur nature` | `Frequency`, `Amplitude (peak)`, `Largest spur amplitude (peak)`, `Spur emergence above the median noise floor`, `SFDR limited by the noise floor` (repris en avertissement) | — |
| `thd` | `THD` (dBc), `THD` (%) | `Frequency`, `Amplitude (peak)`, `Harmonics used` | harmoniques : rang, fréquence, amplitude, dBc ; harmoniques exclues, avec la raison |
| `dynamic` | `SINAD`, `ENOB (full scale)`, `SNR`, `THD`, `SFDR` ; `Dynamic range` si un enregistrement de bruit est fourni | groupes : ajustement ; bruit et distorsion (`Noise + distortion RMS`, `THD+N`, `Noise RMS (harmonics removed)`) ; distorsion harmonique ; raies parasites ; contrôle de cohérence (`SINAD − SINAD(SNR, THD)`) | harmoniques |
| `frequency` | `Frequency` | `Period-to-period dispersion`, `Periods measured`, méthode | fréquence période par période (P2) |
| `period` | `Mean period` | `Standard deviation`, `Minimum`, `Maximum`, `Periods measured` | liste des périodes |
| `delay50` | `Mean delay t(S2) − t(S1)` | `Standard deviation`, `Minimum`, `Maximum`, `Edges paired`, niveau de mesure | Δt de chaque front |
| `coherence` | `Mean coherence in the band` | `Band`, `Welch averages`, `Frequency resolution` | — |
| `spectrogram` | — | `Window duration`, `Displayed frequency resolution`, `Displayed time step`, `Color range` | — |

Comportement :

- Le panneau est accolé au graphique, dans le même onglet ; la séparation est réglable. À 1920×1080, les avertissements, les chiffres clés et le début du détail sont visibles sans défilement.
- Un clic sur une valeur la copie ; `Copy table` copie le détail en texte tabulé (pour un tableur) ; `Export` produit le CSV ou le JSON du résultat.
- P2 : le survol d'une ligne met en évidence l'élément correspondant du graphique (raie parasite, harmonique, bande d'étude, écart maximal au NLNM), et inversement.
- Avec `dynamic`, chaque sous-onglet de figure (SINAD, SFDR, THD) affiche sous son graphique les résultats de l'analyse correspondante ; l'onglet de synthèse les regroupe.
- Un résultat sans mise en page dédiée (script utilisateur) affiche toutes ses valeurs dans le détail.
- Actions de l'onglet : `Edit parameters and re-run`, `Run on another signal`, `Add to report`, `Export` (JSON, CSV, figure), `Ask AI about this result` (joint au chat le résumé du résultat, sans les échantillons).

### 7.6 Comparaison (P2)

- Superposition de plusieurs résultats de même nature dans un même graphique : par exemple DSP de trois numériseurs, ou `lnm` de trois voies.
- Chaque signal garde sa couleur dans toutes les vues : la couleur suit le signal, pas son rang. Cela vaut pour les tracés de plusieurs signaux et pour les comparaisons ; la figure d'un seul résultat garde les couleurs de ses rôles (données, ajustement, modèle).
- Sous le graphique, le panneau de résultats devient un tableau comparatif : une colonne par signal (§7.5).
- Règles de superposition : quand un panneau comporte une courbe lissée (`lnm`), seules les courbes lissées sont superposées ; les modèles (NLNM) sont tracés une fois ; les repères, bandes et conditions de calcul ne sont conservés que s'ils sont identiques pour tous les résultats. Pour `sinad` et `dynamic`, seul le spectre du résidu est comparé.
- Sont refusés, avec la raison : des analyses différentes, des unités différentes (renseigner d'abord l'unité et la sensibilité des signaux), les spectrogrammes (à ouvrir côte à côte). Les analyses sans graphique (`noise`, `frequency`) sont comparées dans le tableau seul.

## 8. Acquisition, temps réel, rapports, scripts et lots

### 8.1 Acquisition SeedLink (P1 — v2 §13.1)

- Formulaire : serveur et port (valeurs de `[seedlink]`), réseau, station ; bouton `List streams` (`INFO STREAMS`), puis choix des voies dans une arborescence filtrable (motifs tels que `FH?`) ; durée ou fenêtre de début et de fin ; dossier et modèle de nom de fichier ; chargement automatique des signaux en fin d'acquisition.
- Pendant l'acquisition : barre de progression globale, tableau par voie (échantillons, dernier échantillon UTC, latence, trous, fréquence effective), état de la connexion et reconnexions, taille du fichier, journal dans `Output`.
- `Stop` arrête proprement l'acquisition (v2 §13.1). En fin d'acquisition : résumé par voie, chemin du fichier, bouton `Open signals`.
- L'acquisition est une tâche du serveur : elle continue si l'onglet ou le navigateur est fermé, et son avancement reste visible dans la barre d'état. Une seule acquisition à la fois (P1) ; plusieurs acquisitions simultanées : P3.

### 8.2 Temps réel (P2 — v2 §13.2)

- Même choix des voies que pour l'acquisition ; durée du tampon et périodes de rafraîchissement configurables.
- Tableau de bord : pour chaque voie, moyenne, écart-type et C-C sur fenêtre glissante (en counts et en unité physique), latence et trous ; trace des dernières secondes ; FFT et DSP de Welch sur fenêtre glissante (défaut 60 s, rafraîchies toutes les 2 s).
- Enregistrement simultané en miniSEED (interrupteur, actif aussi pendant l'exécution) ; arrêt.
- Réception, calcul et affichage découplés (R7, R12) : le navigateur ne reçoit que les statistiques et des courbes décimées.
- Les axes des graphiques suivent les données tant que l'utilisateur n'a pas zoomé ; un double-clic les fait suivre de nouveau. Une session temps réel à la fois ; elle appartient au serveur, comme l'acquisition (§3.4).

### 8.3 Rapports (P1 — v2 §14)

- Panier : `Add to report` depuis un résultat ou depuis l'encart `Objects` ; ordre des résultats modifiable par glisser-déposer.
- Formulaire : titre, auteur, contexte (texte libre ou extrait de `context.md`), formats (HTML, PDF), moteur PDF.
- `Generate` produit le dossier du rapport (`report.qmd` et figures matplotlib, v2 §14) et propose de l'ouvrir dans l'éditeur pour le retoucher.
- `Render` lance `quarto render` en tâche de fond (journal dans `Output`) ; l'aperçu HTML s'ouvre dans un onglet ; le PDF, le HTML ou le dossier complet (archive zip) peuvent être téléchargés.
- Liste des rapports existants (`reports/`), avec aperçu et téléchargement.

### 8.4 Scripts (P1 — v2 §16.1)

- La vue `Scripts` présente les scripts de `scripts/`, découverts automatiquement, avec leur description.
- `New script` crée un script à partir du modèle (`templates/script_template.py`) et l'ouvre dans l'éditeur (§9). Dans le web, cette action remplace `/edit_script` et l'éditeur vi ou nano.
- `Run` : choix des signaux et formulaire généré à partir de `PARAMS` ; le résultat s'ouvre dans un onglet. Sans mise en page dédiée, le graphique utilise la mise en page générique (R11) ; si le script fournit `plot()`, sa figure matplotlib est également affichée, sous forme d'image.
- À l'enregistrement : vérification syntaxique et rechargement du script (v2 §15.5), erreurs signalées dans l'éditeur.

### 8.5 Lots (P2 — v2 §16.2)

- Formulaire : analyse ou script, fichiers (motif, ou sélection dans l'explorateur), paramètres, fichier de sortie (CSV, JSON).
- Avancement fichier par fichier ; tableau des résultats (une ligne par fichier et par voie) ; les erreurs sont consignées sans interrompre le lot.
- Export du tableau ; rapport global en option.
- Les motifs sont relatifs au projet et les fichiers confinés à ses racines (`[web] roots`, §12.2) ; l'arrêt prend effet avant le fichier suivant ; le rapport global est un rapport Quarto contenant le tableau du lot.

## 9. Éditeur de texte Monaco

### 9.1 Objectif (P1)

Éditer dans le navigateur tous les fichiers texte du projet : scripts Python, `context.md`, `onthesignal.toml`, rapports `.qmd`, modèles (`templates/`), fichiers de données texte, notes. Dans le web, l'éditeur remplace l'éditeur externe de la console (vi, nano).

### 9.2 Explorateur de fichiers (P1)

- Arborescence de la racine du projet (racines supplémentaires configurables, §13) ; fichiers cachés masqués par défaut.
- Actions : nouveau fichier ou dossier, renommer, supprimer (avec confirmation), téléverser, télécharger, copier le chemin ; `Load as signal` pour les fichiers de données (miniSEED, texte) ; `Run` pour les scripts.
- Mise à jour automatique lorsque des fichiers changent sur le disque (terminal Python, scripts, acquisition, rapports, autres programmes).
- Les fichiers binaires ne s'ouvrent pas dans l'éditeur. Au-delà d'une taille configurable (défaut 5 Mo), un fichier s'ouvre en lecture seule ou est refusé.

### 9.3 Édition (P1)

- Fonctions standard de Monaco : coloration syntaxique (Python, Markdown et Quarto, TOML, YAML, JSON, CSV, shell), recherche et remplacement, multi-curseurs, repli de code, mini-carte, appariement des parenthèses, raccourcis habituels.
- Onglets avec indicateur de modification ; Ctrl+S enregistre (écriture atomique) ; enregistrement automatique en option ; avertissement à la fermeture d'un fichier modifié.
- Si un fichier ouvert est modifié sur le disque : rechargement automatique s'il n'a pas été modifié dans l'éditeur, sinon choix entre recharger, conserver ou comparer (vue différentielle).
- Le thème de l'éditeur suit celui de l'interface.

### 9.4 Aide à l'écriture de Python (P2)

- Complétion et aide à la signature fondées sur Jedi, qui voit l'API onthesignal **et les objets de la session** : après `S1.`, l'éditeur propose `sensitivity`, `lnm`… La documentation au survol provient des docstrings.
- Diagnostics : erreurs de syntaxe signalées dès la frappe (P1, même vérification que v2 §15.5) ; analyse ruff à l'enregistrement ou après une pause de frappe, affichée en soulignés et dans `Problems` (P2).
- Mise en forme par ruff et navigation vers les définitions : P3.
- Réalisation : la complétion, l'aide à la signature et la documentation au survol sont demandées au serveur, qui répond avec Jedi sur l'espace de noms du terminal Python. ruff utilise la configuration du projet ; hors de `scripts/`, les noms du terminal (`S1`, `noise`…) sont déclarés comme définis, puisque ce code s'exécute dans le terminal.

### 9.5 Exécution depuis l'éditeur (P1)

- `Run script` (F5) pour un script de `scripts/` : formulaire des signaux et de `PARAMS` (§8.4).
- `Run selection` et `Run cell` (Shift+Entrée, cellules délimitées par `# %%`) : le code est exécuté dans le terminal Python (§10), dans l'espace de noms de la session, comme s'il y était saisi. Les signaux créés et les résultats apparaissent dans l'interface (R13).
- Fichiers `.qmd` : `Render` et aperçu (§8.3).

### 9.6 Éditeur et IA (P2)

- `Ask AI about selection` joint la sélection à un message du chat (§11).
- Les modifications de code proposées par l'IA et les scripts générés (`/ai_script`) s'affichent dans une **vue différentielle** Monaco ; l'utilisateur les accepte ou les refuse (en bloc ; bloc par bloc : P3). Rien n'est enregistré ni exécuté sans son accord (v2 §17.6, §17.7).

## 10. Terminal Python

### 10.1 Objectif (P1)

Le terminal de l'interface est un **terminal Python relié à la session** : les signaux y sont des variables, toutes les fonctions d'onthesignal y sont disponibles, et ce qui y est fait apparaît aussitôt dans l'interface, et inversement. C'est l'outil de travail libre sur les signaux, en complément des formulaires et des vues : calculs ponctuels avec numpy, enchaînements d'analyses, essais avant d'écrire un script.

Ce n'est pas un shell du système : il n'exécute que du Python et les commandes `/` d'onthesignal (§2.2).

```text
ots> S1.sensitivity = 40 / 2**24; S1.unit = "V"     # properties panel updated
ots> S4 = S1 - S2                                   # S4 appears in the Objects panel
ots> r = noise(S1, remove_mains=True)               # values table, result tab opened
ots> r["dr"]
135.29
ots> for s in (S1, S2, S3):
...      print(s.name, round(noise(s, show=False)["rms"], 3))
...
S1 1.021
S2 0.998
S3 1.204
ots> /lnm S3                                        # graphical form, then result tab
```

### 10.2 Environnement de travail (P1)

- L'espace de noms est celui de la session, comme dans la console de la v2 (v2 §15.2) :
  - les signaux de la session, sous leur nom (`S1`, `S2`…) ;
  - les résultats de la session, sous leur nom (`R1`, `R2`…, §6.1) ;
  - les fonctions de l'API (`load`, `list_sig`, `noise`, `noise_dsp`, `lnm`, `sinad`, `dynamic`, `make_sine`, `report`…) et les classes `Signal`, `Result` et `Param` ;
  - `np` (numpy), importé d'office ;
  - `_`, valeur de la dernière expression, selon la convention de Python.
- Les échantillons d'un signal peuvent être modifiés : `S4.data = S4.data + offset` décale `S4` de `offset` counts, `S4.data[:100] = 0` modifie des échantillons sur place ; la modification est notée dans l'historique du signal (`samples modified`) et les tracés de `S4` sont redessinés. `S5 = S4 + offset` crée une copie décalée.
- La synchronisation avec la session suit les règles de la console (v2 §5.3) et la règle R13 :
  - affecter un signal à une variable l'enregistre sous ce nom : `S4 = S1 - S2` crée `S4`, qui apparaît aussitôt dans l'encart `Objects` ;
  - `del S4` le retire de la session ;
  - modifier un attribut (`S1.unit = "m/s"`) met à jour les propriétés affichées sous le tracé du signal ;
  - les autres variables (nombres, tableaux numpy, listes…) apparaissent dans le groupe `Variables` de l'encart, et les figures matplotlib dans le groupe `Figures` ;
  - à l'inverse, un signal chargé, renommé ou supprimé depuis l'interface est aussitôt présent, renommé ou absent dans le terminal, complétion comprise.
- Les commandes `/` de la console restent utilisables : `/noise S1 fmax=50`, `/load data/*.mseed`, `/help lnm`. Une commande d'analyse saisie sans paramètre ouvre le formulaire graphique (§7.2) au lieu du formulaire en mode texte. `/ai <question>` envoie la question au chat (§11).

### 10.3 Affichage (P1)

| Saisie | Affichage |
| --- | --- |
| expression dont la valeur est un signal (`S1`) | résumé d'une ligne (nom, NSLC, fréquence d'échantillonnage, durée, unité) ; `S1.print()` pour le détail (v2 §5.1) |
| analyse (`noise(S1)`, `lnm(S3)`) | tableau des valeurs dans le terminal et onglet de résultat dans la zone de travail, comme dans la console (v2 §5.2) ; le `Result` est renvoyé et réutilisable : `r = sinad(S2); r["sinad"]` |
| `S1.show()` | onglet de tracé temporel (§5.2) |
| figure matplotlib créée par le code (`plt.plot(...)`, `plt.show()`) | onglet `Figure` affichant l'image (PNG ou SVG) ; aucune fenêtre ne s'ouvre sur le serveur |
| `print(...)`, sorties standard et d'erreur | dans le terminal |
| avertissement (`OnTheSignalWarning`) | en jaune dans le terminal, et dans `Problems` |
| erreur | message court en rouge ; trace complète si `Show tracebacks` est actif (équivalent de `/debug on`) |

P2 : fonction `plot(x, y, …)` qui trace des tableaux numpy quelconques dans un graphique µPlot interactif, par exemple `plot(f, 10 * np.log10(p))`.

### 10.4 Saisie (P1)

- Invite `ots>` et invite de continuation `...` ; saisie sur plusieurs lignes (blocs `for`, `def`, `with`) avec indentation automatique ; coloration syntaxique ; appariement des parenthèses.
- Complétion par Tab, fondée sur Jedi et sur les objets vivants de la session : attributs et méthodes (`S1.` → `sensitivity`, `slice`, `lnm`…), paramètres des fonctions (`noise(S1, f` → `fmin`, `fmax`), noms des signaux, chemins de fichiers dans les chaînes ; aide à la signature pendant la saisie d'un appel.
- Aide : `help(noise)` ou `noise?` affichent la documentation (docstring, paramètres avec unités et valeurs par défaut) ; `/help` reste disponible.
- Historique persistant, partagé avec la console de la v2 (`[console] history_file`) ; recherche par Ctrl+R.
- Un collage de plusieurs lignes est exécuté comme un bloc.
- Ctrl+C interrompt l'exécution en cours, ou efface la ligne en cours de saisie ; Ctrl+L efface l'écran.
- Liens cliquables dans les sorties : onglet de résultat ouvert, chemins de fichiers (ouverts dans l'éditeur).
- Couleurs 24 bits, défilement de 10 000 lignes (configurable), redimensionnement selon la taille du panneau.

### 10.5 Exécution (P1)

- Le code s'exécute dans un thread dédié du serveur, jamais dans la boucle d'événements (R12) : l'interface reste utilisable pendant un calcul long, et l'onglet du terminal signale l'exécution en cours.
- Une seule exécution à la fois ; une saisie faite pendant ce temps attend son tour, comme dans un terminal classique.
- Interruption par Ctrl+C ou par le bouton `Interrupt` : `KeyboardInterrupt` est levée dans le thread d'exécution. Une fonction compilée (numpy, scipy) n'est interrompue qu'à son retour ; une acquisition ou un temps réel lancés depuis le terminal s'arrêtent proprement (v2 §13).
- Le terminal vit dans le serveur : au rechargement de la page, il est rattaché et son contenu récent réaffiché ; une exécution en cours se poursuit.
- La sélection de l'éditeur (`Run selection`, §9.5) et le code proposé par l'IA (`Run in terminal`, §11.6) sont exécutés dans ce terminal, comme s'ils y avaient été saisis : ils figurent dans son historique.
- Un seul terminal Python par session (P1) ; plusieurs terminaux partageant l'espace de noms : P3.

### 10.6 Réalisation

- Le terminal réutilise le moteur de la console de la v2 (`cli/console.py` : espace de noms, synchronisation avec la session, commandes `/`, gestion des erreurs, saisie par prompt_toolkit), exécuté sur un pseudo-terminal (PTY) et affiché par xterm.js (`ui.xterm`). La console et le terminal web gardent ainsi le même comportement (R17).
- Risque technique : prompt_toolkit exécuté sur un PTY, dans un thread du serveur. Une maquette est réalisée dès le lot W0.
- Alternative : IPython (`TerminalInteractiveShell` avec l'espace de noms de la session), plus riche (commandes magiques comme `%timeit`, affichage enrichi) mais qui oblige à adapter les commandes `/` (§17).
- Solution de repli : terminal web simplifié, avec une zone de saisie multiligne, la complétion et le journal des sorties.

### 10.7 Sécurité (P1)

Comme l'exécution des scripts, le terminal Python exécute du code quelconque avec les droits du compte qui exécute le serveur (`os.system` et `subprocess` restent utilisables). L'interface n'ayant pas d'authentification (§17, point 6), la protection repose sur l'écoute locale et le contrôle de l'origine des connexions (§12) :

- écoute sur la seule boucle locale par défaut ; accès à distance par un tunnel SSH (§12.3) ;
- le réglage `[web] code_execution = false` (P2) désactive ensemble le terminal, l'exécution des scripts et de la sélection, et l'exécution du code proposé par l'IA ;
- l'IA ne saisit jamais rien dans le terminal : le code qu'elle propose n'y est exécuté qu'après affichage et confirmation (v2 §17.7) ;
- les saisies sont conservées dans l'historique du terminal, et les opérations sur les signaux dans l'historique de la session (R9).

## 11. Chat IA

### 11.1 Objectif (P1)

Converser avec l'assistant (v2 §17) dans un panneau latéral, voir ce qu'il exécute, valider ses actions et réutiliser son code. Dans le web, le chat remplace le mode `/ai` de la console ; `/ai <question>` saisi dans le terminal Python envoie la question au chat.

### 11.2 Conversation

- Messages rendus en Markdown, avec tableaux et blocs de code colorés (P1) ; formules LaTeX (P2).
- Saisie sur plusieurs lignes : Entrée envoie, Shift+Entrée passe à la ligne (P1).
- Un message qui commence par `/` exécute la commande, comme dans la console (`/init`, `/lnm S1`) ; `/` ouvre la liste des commandes dans le champ de saisie (P1). `@` cite un signal, un résultat ou un fichier pour le joindre au contexte (P2).
- `Stop` interrompt la génération ; `New chat` démarre une nouvelle conversation (P1). `Regenerate` et modification du dernier message : P2.
- Pendant l'attente, la durée écoulée est affichée, utile avec un modèle local lent (P1). Réponse affichée au fil de la génération (P2 : fournisseurs en mode flux, annexe B). Raisonnement du modèle, lorsqu'il est fourni (Qwen3.8, Claude), dans un bloc repliable (P2).
- Historique des conversations enregistré dans `.onthesignal/chats/`, rouvrable et exportable en Markdown (P2).
- Réalisation (P2) : réponse et raisonnement affichés au fil de la génération (Ollama, Claude, ChatGPT) et interruptibles ; mentions `@` avec suggestions (signaux et résultats sous forme de résumés, fichiers texte du projet limités à 20 000 caractères) ; `Allow for this chat` mémorisé par outil jusqu'au prochain `New chat` ; tokens de la dernière requête rapportés à la taille du contexte.

### 11.3 Appels d'outils (P1)

- Chaque appel est présenté sous forme de carte : fonction et arguments, état (en cours, terminé, refusé, en erreur), durée, résumé du résultat, lien `Open result` vers l'onglet du résultat.
- Les actions soumises à confirmation (v2 §17.7 : écriture ou suppression de fichiers, exécution d'un script, acquisition, code Python proposé) affichent dans la carte les boutons `Allow` et `Deny`, avec le détail de l'action (code complet). `Allow for this chat` : P2.
- Les erreurs renvoyées au modèle sont visibles dans la carte.

### 11.4 Contexte transmis (P1)

- Contenu identique à celui de v2 §17.3 : invite système, `agent.md`, `context.md`, résumé produit par `/init`, état de la session, résultats ; jamais les échantillons bruts, sauf si `send_raw_data = true`.
- Barre d'outils du chat : `Init` (`/init`, avec avancement), `Context` (ouvre `context.md` dans l'éditeur). `Regenerate agent doc` (`/gen_ai_doc`) est disponible dans la palette.
- Indicateur de contexte (P2) : profil, modèle local ou en ligne, nombre de tokens utilisés et taille du contexte (par exemple 9 600 sur 262 144 avec Qwen3.8 sous Ollama, `[ai] context`).
- Pièces jointes (P2) : signaux et résultats (sous forme de résumés), sélection de l'éditeur, fichiers texte du projet (taille limitée). Image d'une figure pour les modèles qui lisent les images : P3, désactivée par défaut pour les fournisseurs en ligne.

### 11.5 Fournisseurs et profils

- Sélecteur du fournisseur et du modèle dans l'en-tête du chat, équivalent de `/model` (P1).
- Profils nommés déclarés dans la configuration (§13), par exemple « Qwen3.8 · GB10 » (Ollama distant, contexte de 262 144 tokens) et « Claude Opus 5.5 » (P2). Vérification de disponibilité : serveur joignable, modèle présent (`/api/tags` d'Ollama), clé d'API présente dans l'environnement.
- Les clés d'API ne sont jamais saisies, affichées ni enregistrées par l'interface : seule leur présence dans l'environnement du serveur est indiquée (v2 §17.1).
- À la première utilisation d'un fournisseur en ligne, une boîte de dialogue demande le consentement et rappelle ce qui est transmis (métadonnées et résultats, pas les échantillons). Le consentement est mémorisé par profil.
- Réalisation : `[ai] profile` désigne le profil par défaut ; `/model <profil>` (console) et la liste `Profile` du chat le changent pour la session ; la disponibilité est vérifiée à l'ouverture du chat et à chaque changement.

### 11.6 Code et scripts proposés par l'IA (P1)

- Blocs de code : `Copy`, `Open in editor`, `Run in terminal` (code affiché, puis confirmation, v2 §17.7 ; exécution dans le terminal Python, §10.5).
- `Generate script…` (`/ai_script`) : le script généré s'ouvre dans l'éditeur, en vue différentielle s'il remplace un fichier existant (§9.6), avec l'en-tête « Generated by AI » ; il est vérifié syntaxiquement et n'est jamais exécuté automatiquement (v2 §17.6).

### 11.7 Sécurité et confidentialité (P1)

Les règles de v2 §17.7 s'appliquent sans changement. S'y ajoutent :

- l'IA ne saisit rien dans le terminal Python et n'accède pas aux fichiers situés hors du projet ;
- les contenus lus dans les fichiers (métadonnées, `context.md`, fichiers joints) sont traités comme des données, jamais comme des instructions ;
- toutes les actions de l'IA figurent dans l'historique, le journal et les rapports ;
- les modèles locaux accessibles sur le réseau (Ollama) n'ont pas d'authentification : ils doivent rester sur un réseau de confiance (voir `ollama.md`).

## 12. Sécurité

### 12.1 Menaces et risques acceptés

L'application permet d'exécuter du code Python (terminal Python, scripts) avec les droits du compte qui l'exécute. Elle n'a pas d'authentification (décision du 2026-11-20, §17) : toute personne ou tout programme qui peut se connecter à son port peut exécuter du code avec ce compte.

Menaces traitées :

- une page web malveillante ouverte dans le même navigateur, qui tenterait d'utiliser le serveur local (requêtes ou connexions WebSocket intersites, rebinding DNS) ;
- un contenu piégé lu par l'IA (§11.7).

Risques acceptés, conséquences de l'absence d'authentification :

- un autre utilisateur du même poste peut se connecter au port local : l'application suppose un poste utilisé par une seule personne ;
- si l'écoute est étendue au réseau (`--host`), toute machine qui peut joindre le port peut exécuter du code : à réserver à un réseau de confiance ; le tunnel SSH est préférable (§12.3).

### 12.2 Exigences (P1)

| Exigence | Détail |
| --- | --- |
| Écoute | `127.0.0.1` par défaut ; toute autre adresse est demandée explicitement (`--host`) et provoque un avertissement au démarrage |
| Authentification | aucune (§17, point 6) |
| Origine | vérification des en-têtes `Origin` et `Host` des requêtes HTTP et des connexions WebSocket (liste d'hôtes autorisés) ; indispensable sans authentification : c'est elle qui empêche une page web d'utiliser le serveur local |
| Réseau | écoute sur une interface réseau possible avec `--host`, avec un avertissement au démarrage ; `code_execution = false` conseillé dans ce cas ; HTTPS en option (`tls_cert`, `tls_key`) pour chiffrer les échanges |
| Exécution de code | réglage `code_execution = false` (P2), qui désactive ensemble le terminal Python, l'exécution des scripts et de la sélection, et l'exécution du code proposé par l'IA : mode présentation, par exemple sur un réseau partagé |
| Fichiers | explorateur, éditeur, téléversements et téléchargements confinés aux racines du projet (chemins normalisés, liens symboliques vérifiés) |
| Téléversements | taille maximale configurable (défaut 1 Go), noms de fichiers assainis |
| Secrets | clés d'API jamais affichées, journalisées ni écrites |
| En-têtes HTTP | politique de sécurité du contenu limitant les scripts à ceux de l'application (ressources embarquées, §3.1) ; interdiction d'intégrer l'application dans le cadre d'un autre site |
| Journal | `.onthesignal/logs/web.log` : connexions (adresse d'origine), connexions refusées, fichiers écrits ou supprimés, actions de l'IA ; les saisies du terminal Python sont conservées dans son historique |

### 12.3 Accès à distance recommandé

Utiliser un tunnel SSH : le serveur reste en écoute locale et l'accès est protégé par l'authentification de SSH.

```bash
ssh -L 8080:127.0.0.1:8080 user@lab-pc
# puis, sur le portable : http://127.0.0.1:8080
```

## 13. Configuration

La configuration (v2 §20) reçoit une section `[web]` et des profils d'IA dans `[ai]`.

| Clé `[web]` | Défaut | Description |
| --- | --- | --- |
| `host` | `"127.0.0.1"` | Adresse d'écoute |
| `port` | `8080` | Port |
| `open_browser` | `true` | Ouvrir le navigateur au lancement |
| `tls_cert`, `tls_key` | `""` | Certificat et clé pour HTTPS (chiffrement des échanges sur le réseau) |
| `allowed_hosts` | `[]` | Hôtes autorisés en plus de l'adresse d'écoute |
| `code_execution` | `true` | Autoriser le terminal Python, l'exécution des scripts et celle du code proposé par l'IA (§12.2) |
| `scrollback` | `10000` | Nombre de lignes conservées dans le terminal Python |
| `roots` | `["."]` | Racines de l'explorateur, relatives au projet |
| `upload_dir` | `"data/uploads"` | Dossier des fichiers téléversés |
| `upload_max_mb` | `1024` | Taille maximale d'un téléversement (Mo) |
| `editor_max_mb` | `5` | Taille maximale d'un fichier ouvert dans l'éditeur (Mo) |
| `theme` | `"auto"` | `"auto"`, `"light"` ou `"dark"` |
| `points_per_pixel` | `2` | Densité de la décimation (R16) |
| `autosave` | `false` | Enregistrement automatique dans l'éditeur |

Exemple :

```toml
[web]
host = "127.0.0.1"
port = 8080
code_execution = true
theme = "auto"

[ai]
profile = "Qwen3.8 · GB10"            # profil par défaut (P2)

[[ai.profiles]]
name = "Qwen3.8 · GB10"
provider = "ollama"
model = "qwen3.8:27b-q8_0"
base_url = "http://<gb10-address>:11434"
context = 262144

[[ai.profiles]]
name = "Claude Opus 5.5"
provider = "anthropic"
model = "claude-opus-5-5"             # clé lue dans ANTHROPIC_API_KEY
```

- Sans profil, les clés actuelles de `[ai]` (`provider`, `model`, `base_url`, `context`) restent le réglage par défaut.
- La vue `Settings` (P2) affiche la configuration fusionnée et l'origine de chaque valeur : défaut, fichier global, fichier du projet, session. `Edit file` ouvre le fichier dans l'éditeur, avec validation TOML à l'enregistrement. Une valeur peut aussi être modifiée pour la session seulement (équivalent de `/config section.key=value`).
- Réalisation : un clic sur une valeur la modifie pour la session (syntaxe TOML) ; l'enregistrement de `onthesignal.toml` dans l'éditeur relit la configuration en conservant les valeurs de la session. Seul le fichier du projet s'ouvre dans l'éditeur, confiné au projet ; les valeurs du fichier global sont affichées.
- Les clés inconnues sont ignorées et signalées, sans erreur. Sur le poste actuel, le fichier global `~/.config/onthesignal/config.toml` contient des clés d'une autre application, qui font échouer l'affichage de `/config` (annexe B).

## 14. Exigences non fonctionnelles

| Domaine | Exigence |
| --- | --- |
| Navigateurs | Firefox et navigateurs Chromium (Chrome, Edge), deux dernières versions majeures, et au minimum Chrome et Edge 121 (exigence de NiceGUI 4) ; Safari ≥ 17.2 : P3 |
| Écran | 1920×1080 de référence ; utilisable à partir de 1366×768 |
| Réactivité | aucune action de l'interface ne reste sans réponse visible plus de 100 ms ; boucle d'événements jamais bloquée plus de 50 ms (R12) |
| Démarrage | serveur prêt en moins de 3 s ; première page affichée en moins de 2 s en local |
| Analyses | durées identiques à celles de la console (v2 §20), surcoût de l'interface inférieur à 300 ms |
| Graphiques | §5.6 |
| Volume | signaux jusqu'à 10⁷ échantillons (v2 §20) ; dix signaux de cette taille dans une même session |
| Mémoire du navigateur | moins de 500 Mo pour une session type (dix onglets de résultats) |
| Hors ligne | aucune ressource externe (CDN, polices, mesure d'audience) ; tout fonctionne sans Internet, sauf SeedLink et l'IA en ligne |
| Robustesse | aucune erreur ne ferme le serveur ; reconnexion automatique du navigateur ; tâches de fond indépendantes du navigateur |
| Plateforme | serveur sous Linux ; Python ≥ 3.11 |
| Installation | `pip install -e ".[web]"` ; commande `onthesignal web` |
| Langue | interface entièrement en anglais (v2 §3.2) |
| Accessibilité | navigation au clavier ; légende dès deux séries ; information jamais portée par la seule couleur (tirets pour les modèles) ; contrastes suffisants dans les deux thèmes |

## 15. Documentation, tests et validation

### 15.1 Documentation (P1, obligatoire)

Les règles de v2 §18 s'appliquent, définition de « terminé » comprise. S'y ajoutent :

- dans le manuel utilisateur, une partie `Web interface` : lancement et accès à distance, disposition, signaux, analyses et résultats, graphiques, éditeur, terminal, chat, acquisition, temps réel, rapports, scripts et lots, configuration `[web]`, sécurité, dépannage ;
- dans la documentation développeur : architecture web, `FigureSpec` et mises en page, composants, événements de session, `UserHost`, tâches de fond, ajout d'une vue, tests ;
- des copies d'écran générées automatiquement par les tests de bout en bout (P3) ;
- la documentation Quarto construite est servie par l'application (`/docs`) et ouverte depuis l'aide contextuelle (chaque champ renvoie à la page de son algorithme).

La définition de « terminé » (v2 §18.5) est complétée par : mise en page `FigureSpec` (ou mise en page générique vérifiée), test de l'interface, page du manuel web.

### 15.2 Tests

- Tests unitaires, sans navigateur : mise en page `FigureSpec` de chaque analyse (séries, repères, échelles, conditions), décimation, configuration `[web]`, sécurité (contrôle de l'origine et de l'hôte, confinement des chemins), événements de session, `UserHost`.
- Encart des objets et panneau de résultats : groupes, effet du clic, alias des résultats ; chiffres clés et détail de chaque mise en page (§7.5).
- Terminal Python, sans navigateur : synchronisation avec la session (affectation, `del`, modification d'un attribut), complétion, interruption, redirection des sorties et des figures.
- Tests d'interface simulés (outil de test `User` de NiceGUI) pour chaque vue et chaque parcours.
- Tests de bout en bout dans un navigateur réel (P2) pour les composants JavaScript : µPlot, Monaco, terminal.
- L'IA est testée avec un fournisseur simulé, comme dans `tests/test_ai.py`.

### 15.3 Cas de validation

| ID | Cas | Résultat attendu |
| --- | --- | --- |
| W-01 | Parcours de toutes les commandes du registre | chacune est accessible depuis la palette et s'exécute depuis son formulaire généré, avec les valeurs par défaut |
| W-02 | `lnm` sur un signal en m/s | deux panneaux synchronisés ; abscisse en fréquence ; NLNM affiché, NHNM masqué par défaut ; valeurs identiques à celles de la console |
| W-03 | `sinad` avec `remove_mains=True` | conditions de calcul au-dessus du spectre, trait rouge à chaque raie secteur supprimée, axe logarithmique |
| W-04 | Tracé d'un signal de 10⁷ échantillons | affichage en moins de 2 s ; zoom sur 1 s : échantillons réels visibles ; pic isolé d'un échantillon visible à tous les niveaux de zoom |
| W-05 | Spectre comportant une raie étroite, décimé | la raie conserve son amplitude après décimation |
| W-06 | `S3 = S1 + S2` dans le terminal Python, puis `del S3` | `S3` apparaît dans l'encart `Objects` en moins de 1 s, dans tous les onglets ouverts, puis disparaît |
| W-07 | Script créé depuis le modèle, erreur de syntaxe, correction, `Run` | erreur signalée à l'enregistrement ; après correction, formulaire de `PARAMS` puis onglet de résultat |
| W-08 | Chat avec un fournisseur simulé : appel de `lnm(S1)`, puis d'une action d'écriture | carte d'appel et onglet de résultat ; confirmation demandée pour l'écriture ; un refus est renvoyé au modèle |
| W-09 | Connexion WebSocket depuis une autre origine ; requête avec un en-tête `Host` inconnu (rebinding DNS) ; chemin `../../etc/passwd` dans l'explorateur | refusés |
| W-10 | Démarrage avec `--host 0.0.0.0` ; puis avec `code_execution = false` | avertissement explicite au démarrage (absence d'authentification) ; puis terminal Python, exécution des scripts et du code de l'IA indisponibles |
| W-11 | Connexion à Internet coupée | toutes les fonctions sauf l'IA en ligne restent disponibles ; aucune requête vers l'extérieur |
| W-12 | Acquisition, fermeture puis réouverture du navigateur | acquisition poursuivie, avancement affiché à la réouverture, fichier complet |
| W-13 | Analyse de 10 s en cours | l'interface reste utilisable (temps de réponse inférieur à 100 ms) |
| W-14 | Rapport de trois résultats | génération, rendu Quarto, aperçu HTML, téléchargement du PDF |
| W-15 | Temps réel, six voies à 100 Hz pendant 1 h | aucune croissance de la mémoire du serveur ni du navigateur |
| W-16 | Rechargement de la page | session, onglets, terminal Python et tâches retrouvés |
| W-17 | Signal chargé depuis l'interface, puis `S4.` et Tab dans le terminal | `S4` est connu du terminal ; la complétion propose ses attributs et ses méthodes |
| W-18 | Boucle de calcul de 60 s dans le terminal, puis Ctrl+C | exécution interrompue (`KeyboardInterrupt`), terminal de nouveau disponible ; interface utilisable pendant le calcul |
| W-19 | `plt.plot(S1.data); plt.show()` dans le terminal | figure affichée dans un onglet `Figure` ; aucune fenêtre ouverte sur le serveur |
| W-20 | `noise(S1)` dans le terminal | tableau des valeurs dans le terminal et onglet de résultat, valeurs identiques à celles obtenues par le formulaire |
| W-21 | Clic sur chaque type d'objet de l'encart : signal, résultat, figure, tableau numpy, nombre | affichage dans un onglet (tracé avec propriétés et statistiques en dessous, résultat, figure, graphique, valeur) ; un second clic ramène l'onglet existant |
| W-22 | Chaque fonction du registre exécutée sur un signal de test | sous le graphique : avertissements, chiffres clés et détail prévus au §7.5, en counts et en unité physique, identiques à la sortie de la console (`to_text()`) |
| W-23 | `r = noise(S1)`, puis `r = noise(S2)` dans le terminal | deux résultats `R1` et `R2` dans l'encart ; l'alias `r` passe de `R1` à `R2` |

## 16. Organisation du code et lots de développement

### 16.1 Arborescence proposée

```text
src/onthesignal/
├── host.py                  # interface UserHost (R14)
├── plot/
│   ├── spec.py              # FigureSpec (R11), sans dépendance à l'interface
│   └── layouts/             # mises en page par analyse, mise en page générique
└── web/
    ├── app.py               # lancement (onthesignal web), pages, fichiers statiques
    ├── security.py          # contrôle de l'origine et de l'hôte, confinement des chemins
    ├── state.py             # liaison à la session, événements, tâches de fond
    ├── host.py              # UserHost du web (dialogues, confirmations)
    ├── layout/              # disposition, barre d'activité, palette, barre d'état, panneaux
    ├── views/               # objects, signals, analyses, results, acquisition, realtime, reports,
    │                        # scripts, batch, settings, help
    ├── charts/              # composant µPlot (Python et JavaScript), décimation à la demande
    ├── editor/              # composant Monaco, explorateur, Jedi, ruff
    ├── terminal/            # terminal Python : PTY, moteur de console, complétion, interruption
    ├── chat/                # panneau de chat, cartes d'outils, profils
    └── static/vendor/       # µPlot, Monaco (versions figées, licences)
```

### 16.2 Lots de développement

Chaque lot livre son code, ses tests et sa documentation (définition de « terminé », v2 §18.5).

| Lot | Contenu | Priorité |
| --- | --- | --- |
| W0 | Adaptations du code existant (annexe B : session observable, `UserHost`, `FigureSpec` et mise en page générique, origine des paramètres) ; socle web : lancement, contrôles de sécurité (§12), disposition, palette, barre d'état, tâches de fond ; maquette du terminal Python sur PTY | P1 |
| W1 | Encart des objets (groupe `Signals`) ; signaux : chargement (serveur, téléversement, assistant texte), tracé temporel avec décimation et zoom, propriétés et statistiques sous le tracé, sélection, opérations, signaux de test, export | P1 |
| W2 | Analyses : lanceur, formulaires, onglets de résultats avec les résultats sous les graphiques, groupe `Results` de l'encart, composant µPlot ; mises en page de `noise`, `noise_fft`, `noise_dsp` et `lnm` | P1 |
| W3 | Sinus : `sinefit`, `sinad`, `sfdr`, `thd`, `dynamic` ; rapports | P1 |
| W4 | Éditeur Monaco : explorateur, édition, enregistrement, vérification syntaxique ; scripts (création, exécution) ; exécution de la sélection | P1 |
| W5 | Terminal Python : espace de noms de la session et synchronisation, commandes `/`, complétion, aide, historique, interruption, affichage des résultats et des figures, groupes `Variables` et `Figures` de l'encart, rattachement après rechargement | P1 |
| W6 | Chat IA : conversation, cartes d'outils, confirmations, choix du modèle, `/init`, contexte, code et scripts proposés | P1 |
| W7 | Acquisition SeedLink | P1 |
| W8 | Temps réel ; mesures, `coherence`, `spectrogram` ; lots ; comparaison de résultats | P2 |
| W9 | Confort : thème sombre, complétion Jedi, diagnostics ruff, chat au fil de l'eau et historique, profils d'IA, mentions `@`, vue `Settings` | P2 |

## 17. Décisions sur les points ouverts

Les propositions ont été examinées le 2026-11-20 : toutes sont validées, sauf l'authentification (point 6), abandonnée ; les priorités et l'ordre des lots sont validés tels que proposés (point 15). Ces décisions sont intégrées dans le corps du document (v1.3).

| # | Sujet | Décision |
| --- | --- | --- |
| 1 | Modèle d'utilisation | Une instance = un utilisateur = un projet = une session ; plusieurs onglets synchronisés ; pas de multi-utilisateur (§3.4) |
| 2 | Moteur du terminal Python | Moteur de la console de la v2 (prompt_toolkit) exécuté sur un PTY dans le serveur ; IPython en alternative ; repli sur un terminal web simplifié si la maquette du lot W0 échoue (§10.6) |
| 3 | Rendu des figures | `FigureSpec` pour le web (R11) ; figures matplotlib des rapports inchangées ; leur passage à `FigureSpec` est envisagé en P3 |
| 4 | Figures des rapports | matplotlib côté serveur (qualité d'impression), pas d'export µPlot (§5.5) |
| 5 | Terminal | Terminal Python relié à la session, sans shell du système ; exécution de code désactivable par `code_execution = false` (§10) |
| 6 | Authentification | **Aucune** : la proposition d'un jeton d'accès est abandonnée. En contrepartie : écoute locale par défaut, contrôle de l'origine des connexions, avertissement en cas d'écoute sur le réseau, accès à distance par tunnel SSH (§12) |
| 7 | Complétion Python | Jedi dans le serveur ; serveur de langage (LSP) en P3 si nécessaire (§9.4) |
| 8 | Priorité de l'IA | Chat en P1 (§11) |
| 9 | Profils d'IA | `[[ai.profiles]]` dans la configuration (P2) ; `[ai]` reste le réglage par défaut (§13) |
| 10 | Téléversements | Enregistrés dans `data/uploads/` du projet, 1 Go au maximum (§6.3) |
| 11 | Thème sombre | P2, avec une palette validée sur fond sombre (§4.8) |
| 12 | Application de bureau | Fenêtre native (pywebview) en P3 (§2.3) |
| 13 | Encart des objets | Toujours visible en haut de la colonne de gauche ; il remplace les vues séparées des signaux et des résultats ; les résultats reçoivent des noms de session (`R1`, `R2`…) (§6.1) |
| 14 | Résultats sous les graphiques | Panneau propre à chaque fonction, défini dans sa mise en page (R11) ; chiffres clés du §7.5 validés |
| 15 | Priorités et ordre des lots | Validés tels que proposés (§2.1, §16.2) |

## Annexe A — Correspondance console → interface web

| Console (v2 §15.4) | Interface web |
| --- | --- |
| `/load`, `load(...)` | explorateur (`Load as signal`), `Open…`, téléversement, glisser-déposer, assistant pour les fichiers texte (§6.3) |
| `/make_sine`, `/make_noise` | `New test signal` (§6.5) |
| `/list`, `list_sig()` | encart `Objects`, groupe `Signals` (§6.1) |
| `/info`, `S.print()` | panneau sous le tracé du signal (§6.2) |
| `/show`, `S.show()` | clic sur le signal dans l'encart : tracé temporel (§5.2, §6.2) |
| `/rename`, `/rm` | encart `Objects` : double-clic pour renommer, `Delete` (§6.1) |
| `/export`, `S.save()` | `Export…` (§6.5) |
| `S1 + S2`, `2 * S`, `S.slice()`, `S.copy()` | `New signal from expression`, `Slice`, `Copy` (§6.5) ; terminal Python (§10) |
| analyses du registre : `/noise`, `/noise_fft`, `/noise_dsp`, `/lnm`, `/sinefit`, `/sinad`, `/sfdr`, `/thd`, `/dynamic`, `/frequency`, `/period`, `/delay50`, `/coherence`, `/spectrogram` | lanceur générique, formulaire, onglet de résultat (§7) |
| `/results`, `list_res()` | encart `Objects`, groupe `Results` (§6.1) |
| `/report` | vue `Reports` (§8.3) |
| `/acq` | vue `Acquisition` (§8.1) |
| `/rt` | vue `Real time` (§8.2) |
| `/scripts`, `/run_script` | vue `Scripts` (§8.4) |
| `/edit_script` | éditeur Monaco (§9) |
| `/batch` | traitement par lots (§8.5) |
| `/help` | vue `Help`, palette, aide des champs (§4.2, §7.2) |
| `/config` | vue `Settings`, édition de `onthesignal.toml` (§13) |
| `/debug on`, `/debug off` | réglage `Show tracebacks` (§4.6) |
| `/clear` | Ctrl+L dans le terminal Python ; `Clear` du panneau `Output` |
| `/quit` | `Shut down server` (§3.4) |
| `/ai`, `/ai <question>` | panneau de chat (§11) ; `/ai <question>` dans le terminal Python |
| `/init` | bouton `Init` du chat (§11.4) |
| `/context` | bouton `Context` du chat : `context.md` dans l'éditeur (§11.4) |
| `/model` | sélecteur de modèle, profils (§11.5) |
| `/ai_script` | `Generate script…` (§11.6) |
| `/gen_ai_doc` | palette : `Regenerate agent doc` (§11.4) |
| expressions Python | terminal Python (§10) ; `Run selection` dans l'éditeur (§9.5) |

## Annexe B — Adaptations du code existant

Ces adaptations ont été relevées dans le code actuel. Elles sont réalisées au lot W0, sans changer le comportement de la console.

| Élément | État actuel | Adaptation |
| --- | --- | --- |
| Assistant IA (`ai/assistant.py`) | dépend de la console : affichage par `console.display`, confirmations par `console.ask` (bloquant) | interface `UserHost` (R14), confirmations asynchrones, annulation des requêtes |
| Fournisseurs d'IA (`ai/providers.py`) | réponse complète en une fois, sans nombre de tokens consommés | mode flux et nombre de tokens consommés (P2) |
| Session (`core/session.py`) | dictionnaires modifiés directement, sans notification ; session unique globale (`get_session`) | événements (R13) et verrou ; la session unique reste valable (une instance = une session) |
| Affichage (`session.display_handler`) | point d'entrée existant, utilisé par la console | implémentation web : ouverture d'un onglet de résultat |
| Rendu (`plot/`) | figures matplotlib uniquement | `FigureSpec` et mises en page par analyse (R11) ; tests de cohérence avec les figures matplotlib |
| Décimation (`Curve.to_dict(max_points)`) | sous-échantillonnage régulier, qui peut faire disparaître un pic ou une raie | enveloppe min/max (`minmax_envelope`, déjà présente dans `processing`) pour les traces, décimation conservant les maximums pour les spectres (R16) |
| Paramètres (`resolve_params`) | renvoie les valeurs sans leur origine | variante qui renvoie aussi l'origine de chaque valeur (§7.2) |
| Configuration (`core/config.py`, `/config`) | les clés hors section d'un fichier global étranger font échouer l'affichage de `/config` | clés inconnues ignorées et signalées ; section `[web]` et profils d'IA |
| Console (`cli/console.py`) | entrée et sortie du terminal courant ; exécution dans le thread de la saisie | entrée et sortie configurables (PTY) pour le terminal Python (§10.6) ; exécution dans un thread dédié, interruptible ; formulaires graphiques pour les commandes `/` ; `/ai` renvoyé vers le chat |
| Figures matplotlib du code utilisateur | `plt.show()` ouvre une fenêtre | moteur `Agg` ; figures capturées et affichées dans un onglet `Figure` (§10.3) |
| Résultats de la session (`Session.add_result`) | liste sans nom | nom de session stable (`R1`, `R2`…) exposé dans l'espace de noms du terminal ; alias des variables ; suppression (§6.1) |
| Variables du terminal | non publiées | inventaire des variables de l'espace de noms (type, taille, aperçu), publié vers l'encart après chaque exécution (R13) |
| Panneau de résultats | `Result.rows()` fournit libellé, valeur et équivalent physique | réutilisé tel quel ; la mise en page (R11) ajoute les chiffres clés, les groupes et les tableaux de chaque fonction (§7.5) |
| Acquisition et temps réel (`seedlink/`) | déjà en tâche de fond, avec rappels d'avancement (R7) | pas d'adaptation de fond : l'interface lit les instantanés (R12). Ajouts du lot W8 : dernières secondes de chaque voie (`latest`), FFT ou DSP à la demande (`snapshot(spectrum=…)`), enregistrement activé ou arrêté en cours d'exécution (`set_record_dir`). Correction : avec ObsPy 1.5, la connexion à un vrai serveur échouait toujours (délai de connexion absent) |
| Lots (`scripts.batch`) | tableau rendu à la fin du lot | suivi fichier par fichier (`on_progress`), arrêt entre deux fichiers (`should_stop`), résultat `batch` pour le rapport global (`batch_summary`) |
| Dépendances (`pyproject.toml`) | `web = ["nicegui"]` | NiceGUI 4 (`nicegui>=4.0,<5`) et Jedi (ruff en P2) ; bibliothèques JavaScript embarquées (§3.1) |

## Annexe C — Références

- NiceGUI, documentation : <https://nicegui.io/documentation> ; élément `ui.xterm` : <https://nicegui.io/documentation/xterm>.
- NiceGUI 4.0, notes de version et guide de migration : <https://github.com/zauberzeug/nicegui/releases/tag/v4.0.0>.
- µPlot : <https://github.com/leeoniya/uPlot>.
- Monaco Editor : <https://microsoft.github.io/monaco-editor/>.
- xterm.js : <https://xtermjs.org>.
- Jedi : <https://jedi.readthedocs.io>.
- ruff : <https://docs.astral.sh/ruff/>.
- OWASP, *WebSocket Security Cheat Sheet* (connexions WebSocket intersites, contrôle de l'origine) : <https://cheatsheetseries.owasp.org/cheatsheets/WebSocket_Security_Cheat_Sheet.html>.
- Jupyter Server, modèle de sécurité (contrôle de l'origine et de l'hôte), source d'inspiration pour le §12 : <https://jupyter-server.readthedocs.io/en/latest/operators/security.html>.
- `onthesignal_v2.md` (cahier des charges de la phase 1) ; `ollama.md` (IA locale sur un GB10).
