import time
import os

def sync_data_folder(local_folder, remote_user, remote_host, remote_folder, interval=60):
    """
    Synchronise le dossier local avec le dossier distant via SCP toutes les X secondes.
    Nécessite que la clé SSH soit déjà configurée pour éviter la saisie du mot de passe.
    """
    while True:
        # Commande SCP récursive
        cmd = f'scp -r "{local_folder}/*" {remote_user}@{remote_host}:"{remote_folder}/"'
        print(f"Synchronisation: {cmd}")
        os.system(cmd)
        time.sleep(interval)

if __name__ == "__main__":
    # À personnaliser :
    LOCAL_FOLDER = r"C:/chemin/vers/data"  # Dossier local à synchroniser
    REMOTE_USER = "user"                   # Utilisateur SSH
    REMOTE_HOST = "serveur.com"           # Hôte SSH (Railway/VPS)
    REMOTE_FOLDER = "/app/data"           # Dossier distant sur le serveur
    INTERVAL = 60                          # Intervalle en secondes

    sync_data_folder(LOCAL_FOLDER, REMOTE_USER, REMOTE_HOST, REMOTE_FOLDER, INTERVAL)
