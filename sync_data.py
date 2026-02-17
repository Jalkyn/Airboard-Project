def sync_data_folder(local_folder, remote_user, remote_host, remote_folder, interval=60):

import time
import os
import shutil
import subprocess

def sync_data_folder(local_folder, remote_user, remote_host, remote_folder, interval=60):
    """
    Synchronise le dossier local avec le dossier distant via rsync (si dispo) ou scp toutes les X secondes.
    Nécessite que la clé SSH soit déjà configurée pour éviter la saisie du mot de passe.
    """
    while True:
        # Utilise rsync si disponible (plus efficace, gère les suppressions et fichiers cachés)
        rsync_cmd = f'rsync -avz --delete "{local_folder}/" {remote_user}@{remote_host}:"{remote_folder}/"'
        try:
            result = subprocess.run(["rsync", "--version"], capture_output=True)
            if result.returncode == 0:
                print(f"Synchronisation (rsync): {rsync_cmd}")
                os.system(rsync_cmd)
            else:
                raise Exception()
        except Exception:
            # Fallback sur scp si rsync non dispo
            scp_cmd = f'scp -r "{local_folder}"/* {remote_user}@{remote_host}:"{remote_folder}/"'
            print(f"Synchronisation (scp): {scp_cmd}")
            os.system(scp_cmd)
        time.sleep(interval)

if __name__ == "__main__":
    # À personnaliser :
    LOCAL_FOLDER = r"C:/chemin/vers/data"  # Dossier local à synchroniser
    REMOTE_USER = "user"                   # Utilisateur SSH
    REMOTE_HOST = "serveur.com"           # Hôte SSH (Railway/VPS)
    REMOTE_FOLDER = "/app/data"           # Dossier distant sur le serveur
    INTERVAL = 60                          # Intervalle en secondes

    sync_data_folder(LOCAL_FOLDER, REMOTE_USER, REMOTE_HOST, REMOTE_FOLDER, INTERVAL)
