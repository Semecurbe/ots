# Onthesignal — Cahier des charges

L'objectif de ce document est de décrire avant implémentation les spécifications d'un logiciel de traitement du signal liés à la caractérisation de chaînes sismiques comme l'évaluation du bruit intrinsèque d'un numériseur.

Le deuxième objectif est d'avoir une solution dans un terminal, cli (puis dans un second temps mais avec un cahier des charges modifiés une solution à travers une page web avec nicegui et µplot, cette information est importante afin d'avoir des paradigme de programmation compatible directement avec une implémentation web)

# Principe

L'analyse des signaux se feront principalement sur des signaux statiques miniseed.

Cependant on pourra faire des analyses sur des flux sismiques seedlink mais l'analyse se limitera à mesure la moyenne, l ecart type, le crête à crête sur le signal ou de faire en temps réel une fft ou une dsp de welch.


# Paradigme

Application en python avec les librairies comme numpy, obspy et scipy.

Les signaux sercont considéré comme des objets ou les attributs seront par exemple la fréquence d'échantillonnage, le nom de la station, la location, la voie,...., on pourra additionne deux signaux enfaisant une interpolation s'il on des temps cohérents. Si on fait par exemple 2 fois un signal, le constructeur permettra de multiplier par deux l'amplitude du signal.
On a également un champs sensibilité qui est un coefficient qui permet de passer à des lsb à une valeur physique et on aura également un attribut unité.

Exemple :

Si on fait s.print(), on voit l'ensemble des paramètres du signal.

Si on fait s.show() on affiche le signal dans une fenêtre matplotlib

# Comparaison avec le low noise model

Si on choisit un signal et que l'on fait s.lnm() on compare la dsp du signal en fonction du gabarit, en utilisant la sensibilité et l'unité. Par contre si unité en m, le lnm est fait en déplacement mais si m/s en vitesse et si m/s2 en acceleration.

La comparaison s'effectue dans une fenetue dans une fenetre matplotlib avec en haut la dsp et le gabarit et endessous , l'ecart entre les deux dans un deuxieme graphique en dessous du premier.

exemple :

lnm(s)

# Fichier capable de lire

Fichier miniseed

Fichier texte avec plusieurs colonnes (l utilisateur dira le nombre de voies et s'il y a une colonne dédié pour le temps)

# Analyse de bruit

Je veux pouvoir analyser le bruit du signal en définissant une bande passante d'étude (par défaut un passe bas à 100 Hz) et en prposant de supprimer l'impact du 50 Hz et des harmoniques. Je veux que sur ce bruit tu me calcule le bruit RMS, C-C et la moyenne.

Je veux que tu affiches également la dynamique (dynamic range) ratio entre 20*np.log10(PE/(2*np.sqrt(2))/bruit_rms), dans le menu de la fonction, on doit pouvoir choisir le nombre de bis avec un champs 2**24 par défaut.

Exemple :

noise(S)

Je veux également que si je fais noise_fft(S) j'affiche la fft du signal avec matplotlib et j'affiche les information sur le graphique.

Je veux également que si je fais noise_dsp(S) j'affiche la dsp de welch du signal avec matplotlib et j'affiche les informations sur le graphque du bruit.

# Analyse SINAD et ENBOB

Je veux pouvoir récupéerer le buit sur sinus en utilisant la methode des 4 paramètres. Ensuite je veux que tu prenes le residus et que tu calcules dessus le bruit rms en offrant la possibilité de choisir la bande passante (par defaut filtre passe bas entre 0 et 100 Hz). je veux que tu offres également la possibilité de supprimer le 50 hz et les harmoniques sur le residus pour calculer le bruit rms.

# Analyse SFDR

Je veux la même chose avec le SFDR que le SINAD avec des options équivalentes.

exemple :

SFDR(S)

# Analyse THD

Je veux la même chose avec le THD que le SINAD avec des options équivalentes.

exemple :

THD(S)

# Analyse dynamique 

Je veux que l'ensemble des analyses SINAD, THD et SFDR soit effectués simultanément afin d'avoir toutes les données. Je veux avoir la possibilité de générer un rapport qmd avec les images matplotlib crées afin de faire un pdf ou une page web.

# Acquisition de signaux

Les signaux seront acquis avec acq_mseed.py que tu amlioreras si nécessaire. On verra en temps réel en cli l' avancement de l acquisition.

# IA

Je veux pouvoir btancher un modele comme claude, chatgpt ou un ollama.

Ce modele doit pouvoir interargir avec les objets en mettant un fichier md afin qu il sache quel fonction executé pour faire ce que l'on lui demande, par exemple si je lui dis affiche moi le bruit du modele et compare le au lnm il devra utiliser lnm(S).

Il devra également avoir assez de contexte pour comprendre analyser le signal si nécessaire. 

IA devra également permettre de créer des scripts via un prompts dédié pour des fonctions qui ne sont pas encore defini. 

Je veux quand faisant /init il regarde tous les signaux pour se faire un contexte.

Je veux pouvoir également me créer un fichier de contexte pour qu'il puisse s alimenter et faciliter analyse.

# Mesure

Je veux pour chaque paramètre suivant une fonction distincte :

* Fréquence 
* période 
* temps de passage à 50 % entre deux signaux

# Analyse de cohérence

Je veux que tu me fasses une fonction qui mesre la cohérence entre deux signaux et que tu m'affiches le résultats sous forme d'un graphe matplotlib

# Affichage d'un spectrogramme

Je veux que tu me prenne un signal et que tu me calcule un spectrogramme.

# Template de fonction

Je veux que tu me crées un fichier de fonction standard qui me permet de créer des scipts stanardisé afin de facilité la mise en série de calcul.


# Présentation de IHM

IHM tourne dans un terminal linux. Je veux pourvoir lister tous les objets en cours avec list_sig().

Je veux avoir une utilisation un peu comme opencode afin de faire apparaitre avec "/" l'ensemble des fonctionnalité disponible.

Je veux pouvoir si je choisis par exemple /edit_script "nom du scipt" me permettre d' ecrire un script avec vi ou nano.

