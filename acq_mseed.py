#!/usr/bin/env python3
"""
Acquisition d'un flux SeedLink avec sélection interactive des voies disponibles.

Le script interroge d'abord le serveur (requête INFO STREAMS) pour lister les
voies réellement diffusées pour NETWORK/STATION, puis laisse l'utilisateur
choisir celle(s) à acquérir avant de démarrer le flux temps réel.
"""
import sys
import time
import threading
import xml.etree.ElementTree as ET

import numpy as np
from obspy.clients.seedlink.easyseedlink import create_client
from obspy import Stream

# --- Configuration ---
SERVER   = "10.16.0.188"
SERVER   = "10.16.0.163"

NETWORK  = "RD"
STATION  = "DSMC"
STATION  = "SN270"

DURATION = 110
OUTPUT   = "acquisition_FHZ.mseed"

# --- Stockage ---
st = Stream()
lock = threading.Lock()


def handle_data(trace):
    with lock:
        st.append(trace)


def list_streams(xml_info, network=None, station=None):
    """Parse la réponse INFO STREAMS et renvoie une liste (net, sta, loc, cha)."""
    root = ET.fromstring(xml_info)
    streams = []
    for st_elem in root.findall("station"):
        net, sta = st_elem.get("network"), st_elem.get("name")
        if network and net != network:
            continue
        if station and sta != station:
            continue
        for s in st_elem.findall("stream"):
            loc = s.get("location", "") or ""
            streams.append((net, sta, loc, s.get("seedname")))
    return sorted(set(streams))


def choose_streams(streams):
    """Affiche les voies disponibles et laisse l'utilisateur choisir."""
    if not streams:
        print("Aucune voie disponible pour cette station sur le serveur.")
        sys.exit(1)

    print("\nVoies disponibles :")
    for i, (net, sta, loc, cha) in enumerate(streams, start=1):
        print(f"  {i:2d}) {net}.{sta}.{loc or '--'}.{cha}")

    raw = input("\nNuméros des voies à acquérir (ex: 1,3 ou 'all') : ").strip().lower()
    if raw == "all":
        return streams

    chosen = []
    for part in raw.split(","):
        part = part.strip()
        if part.isdigit() and 1 <= int(part) <= len(streams):
            chosen.append(streams[int(part) - 1])

    if not chosen:
        print("Aucune sélection valide, arrêt.")
        sys.exit(1)
    return chosen


# --- Connexion et découverte des voies ---
print(f"Connexion à {SERVER}...")
client = create_client(SERVER, on_data=handle_data)

print("Interrogation du serveur (INFO STREAMS)...")
xml_info = client.get_info("STREAMS")
available = list_streams(xml_info, network=NETWORK, station=STATION)
selection = choose_streams(available)

# --- Abonnement aux voies choisies ---
for net, sta, loc, cha in selection:
    selector = f"{loc}{cha}"  # format LLCCC attendu par SeedLink (loc puis canal, sans point)
    client.select_stream(net, sta, selector)
    print(f"  → abonnement {net}.{sta}.{loc}.{cha}")

print(f"\nAcquisition de {len(selection)} voie(s) pendant {DURATION}s\n")

t_start = time.time()
thread = threading.Thread(target=client.run, daemon=True)
thread.start()

# --- Barre de progression ---
try:
    while True:
        elapsed = time.time() - t_start
        if elapsed >= DURATION:
            break
        pct = min(elapsed / DURATION * 100, 100)
        bar = int(pct // 2)
        with lock:
            n_traces = len(st)
        sys.stdout.write(
            f"\r  [{'█' * bar:<50}] {pct:5.1f}%  "
            f"{elapsed:.0f}/{DURATION}s  —  {n_traces} trace(s) reçues"
        )
        sys.stdout.flush()
        time.sleep(0.5)
except KeyboardInterrupt:
    print("\n\nInterrompu par l'utilisateur.")

# --- Fermeture ---
client.close()
print("\n\nFin de l'acquisition.")

st.merge(method=1, fill_value="interpolate")
if len(st) == 0:
    print("Aucune donnée reçue, rien à enregistrer.")
    sys.exit(1)

st.write(OUTPUT, format="MSEED")
print(f"Enregistré : {OUTPUT}\n")
print(st)

# --- Statistiques par voie ---
print("\n" + "=" * 60)
print("  STATISTIQUES PAR VOIE")
print("=" * 60)

for net, sta, loc, cha in selection:
    traces = st.select(channel=cha, location=loc)
    if len(traces) == 0:
        print(f"  {cha} : aucune donnée reçue")
        continue
    data = np.concatenate([tr.data for tr in traces])
    print(f"  {cha} :  N={len(data):>10}   "
          f"moyenne={np.mean(data):>14.6f}   "
          f"écart-type={np.std(data):>14.6f}")

print("=" * 60)