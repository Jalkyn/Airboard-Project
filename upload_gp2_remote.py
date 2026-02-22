#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
upload_gp2_remote.py
---------------------
Script local à exécuter sur la machine qui génère les fichiers GP2.
Il surveille le dossier local de données et envoie automatiquement
chaque nouveau fichier GP2_*.txt au backend Railway via HTTP POST.

Usage :
    1.  Configurer les variables ci-dessous (ou via .env / variables d'env) :
            - LOCAL_DATA_DIR   : chemin local du dossier de données GP2
            - REMOTE_SERVER_URL: URL du backend Railway (ex: https://mon-projet.up.railway.app)
            - UPLOAD_API_KEY   : clé API pour l'authentification (doit correspondre côté serveur)
    2.  Lancer le script :
            python upload_gp2_remote.py
    3.  Le script tourne en boucle et uploade chaque nouveau fichier toutes les INTERVAL secondes.
"""

import os
import re
import sys
import time
import json
import logging
import argparse
import requests
from pathlib import Path
from datetime import datetime

# ---- Configuration par défaut (modifiable via arguments CLI ou variables d'env) ----

# Dossier local contenant les fichiers GP2_*.txt générés par la station
LOCAL_DATA_DIR = os.environ.get("LOCAL_DATA_DIR", r"C:\chemin\vers\data")

# URL du serveur Railway (sans slash final)
REMOTE_SERVER_URL = os.environ.get("REMOTE_SERVER_URL", "https://votre-projet.up.railway.app")

# Clé API d'upload (doit correspondre à UPLOAD_API_KEY sur le serveur)
UPLOAD_API_KEY = os.environ.get("UPLOAD_API_KEY", "")

# Intervalle en secondes entre chaque vérification
INTERVAL = int(os.environ.get("UPLOAD_INTERVAL", "60"))

# Regex pour les fichiers GP2 valides
FNAME_REGEX = re.compile(r"GP2_(\d{2}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\.txt$")

# Fichier de suivi des uploads (pour ne pas re-uploader les mêmes fichiers)
UPLOAD_TRACKER_FILE = ".uploaded_gp2_files.json"

# ---- Logging ----
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("upload_gp2")


def load_uploaded_set(tracker_path: Path) -> set:
    """Charge la liste des fichiers déjà uploadés."""
    if tracker_path.exists():
        try:
            data = json.loads(tracker_path.read_text(encoding="utf-8"))
            return set(data.get("uploaded", []))
        except Exception:
            return set()
    return set()


def save_uploaded_set(tracker_path: Path, uploaded: set):
    """Sauvegarde la liste des fichiers uploadés."""
    data = {"uploaded": sorted(uploaded), "last_update": datetime.now().isoformat()}
    tracker_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def upload_file(server_url: str, api_key: str, filepath: Path) -> bool:
    """
    Envoie un fichier GP2 au serveur distant.
    Retourne True si l'upload a réussi, False sinon.
    """
    url = f"{server_url.rstrip('/')}/api/upload-gp2"
    headers = {}
    if api_key:
        headers["X-Api-Key"] = api_key

    try:
        with open(filepath, "rb") as f:
            response = requests.post(
                url,
                files={"file": (filepath.name, f, "text/plain")},
                headers=headers,
                timeout=30,
            )
        if response.status_code == 200:
            result = response.json()
            logger.info(
                f"✅ Upload réussi: {filepath.name} "
                f"({result.get('size', '?')} octets, "
                f"{result.get('files_in_data', '?')} fichiers sur le serveur)"
            )
            return True
        else:
            logger.error(
                f"❌ Upload échoué ({response.status_code}): {filepath.name} — "
                f"{response.text[:200]}"
            )
            return False
    except requests.exceptions.ConnectionError:
        logger.error(f"❌ Connexion impossible à {url} — Vérifiez l'URL du serveur")
        return False
    except requests.exceptions.Timeout:
        logger.error(f"❌ Timeout lors de l'upload de {filepath.name}")
        return False
    except Exception as e:
        logger.error(f"❌ Erreur inattendue: {e}")
        return False


def check_server_health(server_url: str) -> bool:
    """Vérifie que le serveur est accessible."""
    try:
        resp = requests.get(f"{server_url.rstrip('/')}/api/health", timeout=10)
        return resp.status_code == 200
    except Exception:
        return False


def run_once(data_dir: Path, server_url: str, api_key: str, tracker_path: Path) -> int:
    """
    Vérifie les nouveaux fichiers et les uploade.
    Retourne le nombre de fichiers uploadés.
    """
    if not data_dir.exists():
        logger.error(f"Dossier local introuvable: {data_dir}")
        return 0

    uploaded_set = load_uploaded_set(tracker_path)
    count = 0

    # Trouver tous les fichiers GP2 valides
    gp2_files = []
    for f in data_dir.iterdir():
        if f.is_file() and FNAME_REGEX.search(f.name):
            gp2_files.append(f)

    if not gp2_files:
        logger.debug("Aucun fichier GP2_*.txt trouvé dans le dossier local")
        return 0

    # Trier par date (plus ancien d'abord pour uploader dans l'ordre)
    gp2_files.sort(key=lambda f: f.stat().st_mtime)

    new_files = [f for f in gp2_files if f.name not in uploaded_set]

    if not new_files:
        logger.debug(f"Aucun nouveau fichier ({len(gp2_files)} fichiers déjà uploadés)")
        return 0

    logger.info(f"📤 {len(new_files)} nouveau(x) fichier(s) à uploader")

    for filepath in new_files:
        success = upload_file(server_url, api_key, filepath)
        if success:
            uploaded_set.add(filepath.name)
            save_uploaded_set(tracker_path, uploaded_set)
            count += 1
        else:
            # En cas d'échec, on arrête pour ne pas uploader les suivants dans le désordre
            logger.warning("Arrêt des uploads suite à une erreur")
            break

    return count


def main():
    parser = argparse.ArgumentParser(
        description="Upload automatique des fichiers GP2 vers le serveur Railway"
    )
    parser.add_argument(
        "--data-dir",
        default=LOCAL_DATA_DIR,
        help=f"Dossier local des fichiers GP2 (défaut: {LOCAL_DATA_DIR})",
    )
    parser.add_argument(
        "--server-url",
        default=REMOTE_SERVER_URL,
        help=f"URL du serveur Railway (défaut: {REMOTE_SERVER_URL})",
    )
    parser.add_argument(
        "--api-key",
        default=UPLOAD_API_KEY,
        help="Clé API d'upload (défaut: variable d'env UPLOAD_API_KEY)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=INTERVAL,
        help=f"Intervalle en secondes (défaut: {INTERVAL})",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Exécuter une seule fois puis quitter (pas de boucle)",
    )
    parser.add_argument(
        "--upload-all",
        action="store_true",
        help="Ignorer le tracker et re-uploader tous les fichiers",
    )
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    server_url = args.server_url
    api_key = args.api_key
    tracker_path = data_dir / UPLOAD_TRACKER_FILE

    # Affichage de la configuration
    logger.info("=" * 60)
    logger.info("Upload GP2 → Railway")
    logger.info("=" * 60)
    logger.info(f"  Dossier local  : {data_dir.resolve()}")
    logger.info(f"  Serveur distant: {server_url}")
    logger.info(f"  Clé API        : {'***' + api_key[-4:] if len(api_key) > 4 else '(non définie)' if not api_key else '***'}")
    logger.info(f"  Intervalle     : {args.interval}s")
    logger.info(f"  Mode           : {'une fois' if args.once else 'boucle continue'}")
    logger.info("=" * 60)

    # Vérifier la connexion au serveur
    logger.info("Vérification de la connexion au serveur...")
    if check_server_health(server_url):
        logger.info("✅ Serveur accessible")
    else:
        logger.warning("⚠️  Serveur inaccessible — les uploads seront retentés")

    # Si --upload-all, réinitialiser le tracker
    if args.upload_all:
        logger.info("Mode --upload-all : réinitialisation du tracker")
        if tracker_path.exists():
            tracker_path.unlink()

    if args.once:
        count = run_once(data_dir, server_url, api_key, tracker_path)
        logger.info(f"Terminé : {count} fichier(s) uploadé(s)")
        sys.exit(0)

    # Boucle continue
    logger.info("Démarrage de la surveillance du dossier...")
    while True:
        try:
            run_once(data_dir, server_url, api_key, tracker_path)
        except KeyboardInterrupt:
            logger.info("\nArrêt demandé par l'utilisateur")
            sys.exit(0)
        except Exception as e:
            logger.error(f"Erreur dans la boucle principale: {e}", exc_info=True)

        try:
            time.sleep(args.interval)
        except KeyboardInterrupt:
            logger.info("\nArrêt demandé par l'utilisateur")
            sys.exit(0)


if __name__ == "__main__":
    main()
