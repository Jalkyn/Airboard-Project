#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from datetime import datetime, timedelta
from typing import Any, Dict
import logging

import numpy as np
import pandas as pd
from flask import Flask, jsonify, render_template, request, send_from_directory
import requests
import math
import os
import json
import tempfile

# Charger les variables d'environnement depuis le fichier .env
try:
    from dotenv import load_dotenv
    # Charger le fichier .env depuis le répertoire du serveur
    server_dir = Path(__file__).parent
    env_path = server_dir / '.env'
    if env_path.exists():
        load_dotenv(env_path)
    else:
        # Essayer aussi dans le répertoire parent
        parent_env_path = server_dir.parent / '.env'
        if parent_env_path.exists():
            load_dotenv(parent_env_path)
        else:
            # Essayer dans le répertoire de travail courant
            load_dotenv()
except ImportError:
    # python-dotenv n'est pas installé, continuer sans
    pass

import Windy_Open_Meteo as core
import chatbot_windy
import ml_forecast
import threading

app = Flask(__name__)

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration CORS pour permettre les requêtes depuis l'iframe React et Vercel
try:
    from flask_cors import CORS
    # Permettre toutes les origines en production (sécurisé car les clés API sont côté serveur)
    # En production, vous pouvez restreindre aux domaines spécifiques si nécessaire
    allowed_origins = os.environ.get("ALLOWED_ORIGINS", "https://localhost")
    if allowed_origins == "*":
        origins = ["*"]
    else:
        origins = allowed_origins.split(",")
    
    CORS(app, resources={
        r"/*": {
            "origins": origins,
            "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
            "allow_headers": ["Content-Type", "Authorization", "Cache-Control"],
            "supports_credentials": True
        }
    })
    logger.info(f"CORS activé via flask-cors (origins: {origins})")
except ImportError:
    # Fallback : configuration CORS manuelle si flask-cors n'est pas installé
    allowed_origins = os.environ.get("ALLOWED_ORIGINS", "*")
    
    @app.after_request
    def after_request(response):
        if allowed_origins == "*":
            response.headers.add('Access-Control-Allow-Origin', '*')
        else:
            # Permettre seulement les origines spécifiées
            origin = request.headers.get('Origin')
            if origin and origin in allowed_origins.split(","):
                response.headers.add('Access-Control-Allow-Origin', origin)
        response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization,Cache-Control')
        response.headers.add('Access-Control-Allow-Methods', 'GET,PUT,POST,DELETE,OPTIONS')
        response.headers.add('Access-Control-Allow-Credentials', 'true')
        return response
    logger.info(f"CORS activé manuellement (origins: {allowed_origins})")
    logger.info("CORS activé manuellement (flask-cors non disponible)")


# Autoriser l'embed de l'interface Windy dans une iframe (ex: frontend Vercel)
# Ne pas envoyer X-Frame-Options pour éviter de bloquer l'iframe
@app.after_request
def allow_embed_in_iframe(response):
    # frame-ancestors autorise qui peut mettre cette page en iframe ('self' + origines optionnelles)
    frame_ancestors = os.environ.get("FRAME_ANCESTORS", "self *")
    response.headers["Content-Security-Policy"] = f"frame-ancestors {frame_ancestors}"
    return response


# Verrou pour éviter les appels simultanés à compute_fields() et run_fusion_once()
# Cela évite les conflits entre le chatbot et la mise à jour automatique du frontend
_fusion_lock = threading.Lock()
_last_fusion_result = None
_last_fusion_timestamp = None
_fusion_cache_ttl = 30  # Cache les résultats pendant 30 secondes

# Cache pour les données dashboard (par dossier)
# Structure: {chemin_absolu_dossier: {"data": {...}, "timestamp": datetime, "last_file_mtime": float}}
_dashboard_cache = {}
_dashboard_cache_ttl = 30  # Cache les données dashboard pendant 30 secondes

def compute_fields(use_cache: bool = True, data_dir: Path = None) -> Dict[str, Any]:
    """
    Calcule les champs fusionnés avec verrou pour éviter les conflits.
    
    Args:
        use_cache: Si True, utilise le cache si disponible et récent (< 30s)
        data_dir: (optionnel) Dossier de données personnalisé. Si None, utilise STATION_CFG.data_dir
    
    Returns:
        Dictionnaire avec les données fusionnées
    """
    global _last_fusion_result, _last_fusion_timestamp
    
    # Vérifier le cache d'abord (mais seulement si c'est le même dossier)
    if use_cache and _last_fusion_result is not None and _last_fusion_timestamp is not None:
        from datetime import datetime
        cache_age = (datetime.now() - _last_fusion_timestamp).total_seconds()
        # Ne pas utiliser le cache si un dossier personnalisé est demandé
        if data_dir is None and cache_age < _fusion_cache_ttl:
            return _last_fusion_result
    
    # Acquérir le verrou pour éviter les appels simultanés
    with _fusion_lock:
        # Vérifier à nouveau le cache après avoir acquis le verrou (double-check)
        if use_cache and _last_fusion_result is not None and _last_fusion_timestamp is not None:
            from datetime import datetime
            cache_age = (datetime.now() - _last_fusion_timestamp).total_seconds()
            # Ne pas utiliser le cache si un dossier personnalisé est demandé
            if data_dir is None and cache_age < _fusion_cache_ttl:
                return _last_fusion_result
        
        # Sauvegarder le data_dir original
        original_data_dir = core.STATION_CFG.data_dir
        
        try:
            # Modifier temporairement le data_dir si un dossier personnalisé est fourni
            if data_dir is not None:
                # Vérifier que le dossier existe avant de l'utiliser
                if not data_dir.exists() or not data_dir.is_dir():
                    logger.error(f"Dossier personnalisé n'existe pas: {data_dir}")
                    logger.error(f"Chemin absolu: {data_dir.resolve()}")
                    # Vérifier si le dossier par défaut existe
                    if core.STATION_CFG.data_dir.exists():
                        logger.warning("Utilisation du dossier par défaut à la place")
                        data_dir = None  # Utiliser le défaut
                    else:
                        # Aucun dossier disponible, lever une erreur
                        raise FileNotFoundError(f"Aucun dossier de données disponible. Dossier personnalisé: {data_dir}, Dossier par défaut: {core.STATION_CFG.data_dir}")
                else:
                    logger.info(f"Utilisation du dossier personnalisé pour compute_fields: {data_dir}")
                    logger.info(f"Chemin absolu: {data_dir.resolve()}")
                    # Vérifier qu'il y a des fichiers dans le dossier
                    txt_files = list(data_dir.glob("*.txt"))
                    logger.info(f"Fichiers .txt trouvés dans le dossier: {len(txt_files)}")
                    if txt_files:
                        logger.info(f"Exemples de fichiers: {[f.name for f in txt_files[:5]]}")
                    core.STATION_CFG.data_dir = data_dir
            
            logger.debug("Calcul du champ fusionné (verrou acquis)")
            station_meas, model, fused = core.run_fusion_once(with_plots=False)
        except FileNotFoundError as e:
            # Si le fichier n'est pas trouvé, essayer avec le dossier par défaut (seulement si différent)
            if data_dir is not None and data_dir != original_data_dir:
                logger.warning(f"Fichier non trouvé dans le dossier personnalisé: {e}")
                logger.warning(f"Dossier personnalisé: {data_dir}")
                # Vérifier si le dossier par défaut existe
                if original_data_dir.exists():
                    logger.info("Tentative avec le dossier par défaut...")
                    # Restaurer le data_dir original
                    core.STATION_CFG.data_dir = original_data_dir
                    # Réessayer avec le dossier par défaut
                    try:
                        station_meas, model, fused = core.run_fusion_once(with_plots=False)
                    except FileNotFoundError as e2:
                        logger.error(f"Fichier également non trouvé dans le dossier par défaut: {e2}")
                        raise FileNotFoundError(f"Aucun fichier de données trouvé. Dossier personnalisé: {data_dir}, Dossier par défaut: {original_data_dir}. Erreur: {e}")
                else:
                    logger.error(f"Le dossier par défaut n'existe pas non plus: {original_data_dir}")
                    raise FileNotFoundError(f"Aucun dossier de données disponible. Dossier personnalisé: {data_dir}, Dossier par défaut: {original_data_dir}. Erreur: {e}")
            else:
                # Si c'était déjà le défaut, propager l'erreur avec plus de détails
                logger.error(f"Erreur FileNotFoundError: {e}")
                logger.error(f"Dossier utilisé: {core.STATION_CFG.data_dir}")
                logger.error(f"Dossier existe: {core.STATION_CFG.data_dir.exists()}")
                if core.STATION_CFG.data_dir.exists():
                    # Lister les fichiers pour aider au débogage
                    all_files = list(core.STATION_CFG.data_dir.glob("*.txt"))
                    logger.error(f"Fichiers .txt dans le dossier: {[f.name for f in all_files]}")
                raise
        finally:
            # Restaurer le data_dir original
            if data_dir is not None:
                core.STATION_CFG.data_dir = original_data_dir

        ny, nx = core.GRID_CFG.ny, core.GRID_CFG.nx

        lat_vals = np.linspace(core.GRID_CFG.lat_min, core.GRID_CFG.lat_max, ny)
        lon_vals = np.linspace(core.GRID_CFG.lon_min, core.GRID_CFG.lon_max, nx)
        lat2d, lon2d = np.meshgrid(lat_vals, lon_vals, indexing="ij")

        data = {
            "grid": {
                "lat_min": float(core.GRID_CFG.lat_min),
                "lat_max": float(core.GRID_CFG.lat_max),
                "lon_min": float(core.GRID_CFG.lon_min),
                "lon_max": float(core.GRID_CFG.lon_max),
                "ny": int(ny),
                "nx": int(nx),
            },

            "lat": lat2d.tolist(),
            "lon": lon2d.tolist(),

            "temp": fused.temp_corr.tolist(),
            "rh": fused.rh_corr.tolist(),          # ← IMPORTANT : humidité
            "u": fused.u_corr.tolist(),
            "v": fused.v_corr.tolist(),

            "station": {
                "name": core.STATION_CFG.name,
                "lat": float(core.STATION_CFG.lat),
                "lon": float(core.STATION_CFG.lon),
            },

            "station_timestamp": station_meas.timestamp.isoformat(),

            "station_data": {
                "speed_ms": float(station_meas.speed_ms),
                "dir_deg": float(station_meas.dir_deg),
                "rh": float(station_meas.rh),
                "air_temp_c": float(station_meas.air_temp_c),
            },
        }
        
        # Mettre à jour le cache
        from datetime import datetime
        _last_fusion_result = data
        _last_fusion_timestamp = datetime.now()
        
        return data


@app.route("/api/fields")
def api_fields():
    """
    Endpoint pour récupérer les champs fusionnés.
    Utilise le cache si disponible pour éviter les recalculs inutiles.
    
    Paramètres:
        data_dir: (optionnel) Chemin du dossier de données personnalisé.
                  Si non fourni, utilise le dossier par défaut (core.STATION_CFG.data_dir).
    """
    try:
        # Récupérer le dossier de données (optionnel)
        # D'abord depuis les paramètres de la requête, puis depuis la variable globale
        custom_data_dir = request.args.get("data_dir", None)
        if custom_data_dir is None:
            global _current_data_dir
            custom_data_dir = _current_data_dir
        
        # Utiliser le dossier personnalisé si fourni, sinon None (utilisera le défaut)
        data_dir_to_use = None
        if custom_data_dir:
            # Convertir en Path (essayer d'abord comme chemin absolu, puis relatif)
            custom_path = Path(custom_data_dir)
            
            # Si le chemin n'est pas absolu et n'existe pas, essayer depuis le répertoire parent
            if not custom_path.is_absolute() and not custom_path.exists():
                # Essayer depuis le répertoire du serveur
                server_dir = Path(__file__).parent
                custom_path = server_dir / custom_data_dir
            
            # Vérifier que le dossier existe
            if not custom_path.exists() or not custom_path.is_dir():
                logger.warning(f"Dossier de données personnalisé non trouvé: {custom_path}, utilisation du dossier par défaut")
                logger.warning(f"Chemin demandé: {custom_data_dir}")
                # Utiliser le dossier par défaut au lieu de retourner une erreur
                data_dir_to_use = None
            else:
                # Résoudre le chemin pour comparer avec le dossier par défaut
                resolved_custom = custom_path.resolve()
                default_resolved = core.STATION_CFG.data_dir.resolve()
                
                # Si le chemin résolu correspond exactement au dossier par défaut, utiliser le défaut
                # (pour éviter les problèmes de cache et de cohérence)
                if resolved_custom == default_resolved:
                    data_dir_to_use = None
                    logger.info(f"Chemin résolu correspond au dossier par défaut pour /api/fields, utilisation du défaut")
                else:
                    data_dir_to_use = custom_path
                    logger.info(f"Utilisation du dossier personnalisé pour /api/fields: {data_dir_to_use}")
        
        # Utiliser le cache pour éviter les recalculs si les données sont récentes
        # Le frontend appelle cet endpoint toutes les 60 secondes
        data = compute_fields(use_cache=True, data_dir=data_dir_to_use)
        return jsonify(data)
    except FileNotFoundError as e:
        logger.error(f"Fichier non trouvé: {e}")
        return jsonify({
            "error": "Fichier de données station introuvable",
            "message": str(e),
            "status": "error"
        }), 404
    except requests.RequestException as e:
        logger.error(f"Erreur API Open-Meteo: {e}")
        return jsonify({
            "error": "Erreur lors de la récupération des données météo",
            "message": str(e),
            "status": "error"
        }), 503
    except Exception as e:
        logger.error(f"Erreur inattendue dans compute_fields: {e}", exc_info=True)
        return jsonify({
            "error": "Erreur interne du serveur",
            "message": str(e),
            "status": "error"
        }), 500

@app.route("/api/forecast/ml", methods=["GET"])
def api_forecast_ml():
    """
    Prédictions ML pour la série temporelle des prévisions.
    Utilise les données Open-Meteo corrigées (comme pour le temps réel) pour prédire
    les données au point de la station GP2 avec les 5 modèles ML.
    
    Paramètres:
        hours: Liste des heures à prédire (ex: "0,3,6,9") ou "all" pour 0, 3, 6, 9h (toutes les 3h, max 9h)
        models: Liste des modèles à utiliser (ex: "xgb,lgbm,hgbr") ou "all" pour tous
    """
    try:
        # Récupérer les heures à prédire (toutes les 3 heures jusqu'à 9h maximum)
        hours_param = request.args.get("hours", "all")
        if hours_param == "all":
            hours = list(range(0, 10, 3))  # 0, 3, 6, 9 (toutes les 3h, max 9h)
        else:
            try:
                hours = [int(h.strip()) for h in hours_param.split(",")]
                hours = [h for h in hours if 0 <= h <= 9]  # Limiter à 9h max
                hours.sort()  # Trier pour prédiction séquentielle
            except:
                hours = list(range(0, 10, 3))  # Par défaut: 0, 3, 6, 9
        
        # Récupérer les modèles à utiliser
        models_param = request.args.get("models", "all")
        if models_param == "all":
            model_names = None  # Tous les modèles
        else:
            model_names = [m.strip() for m in models_param.split(",") if m.strip() != "bundle"]  # Exclure "bundle" qui n'est pas un modèle
        
        # Vérifier que les modèles sont chargés
        try:
            available_models = ml_forecast.load_ml_models()
            logger.info(f"Modèles ML disponibles: {list(available_models.keys())}")
            if model_names:
                missing_models = [m for m in model_names if m not in available_models]
                if missing_models:
                    logger.warning(f"⚠️ Modèles demandés mais non disponibles: {missing_models}")
                    logger.warning(f"Modèles disponibles: {list(available_models.keys())}")
        except Exception as e:
            logger.error(f"Erreur lors du chargement des modèles ML: {e}", exc_info=True)
        
        # Position de la station
        station_lat = core.STATION_CFG.lat
        station_lon = core.STATION_CFG.lon
        
        # Récupérer le dossier de données (optionnel)
        # D'abord depuis les paramètres de la requête, puis depuis la variable globale
        custom_data_dir = request.args.get("data_dir", None)
        if custom_data_dir is None:
            global _current_data_dir
            custom_data_dir = _current_data_dir
        
        # Utiliser le dossier personnalisé si fourni, sinon le dossier par défaut
        if custom_data_dir:
            # Convertir en Path (essayer d'abord comme chemin absolu, puis relatif)
            custom_path = Path(custom_data_dir)
            
            # Si le chemin n'est pas absolu et n'existe pas, essayer depuis le répertoire parent
            if not custom_path.is_absolute() and not custom_path.exists():
                # Essayer depuis le répertoire du serveur
                server_dir = Path(__file__).parent
                custom_path = server_dir / custom_data_dir
            
            # Vérifier que le dossier existe
            if not custom_path.exists() or not custom_path.is_dir():
                return jsonify({
                    "error": "Dossier de données personnalisé non trouvé",
                    "data_dir": str(custom_path),
                    "data_dir_requested": custom_data_dir,
                    "status": "error"
                }), 404
            
            # Résoudre le chemin pour comparer avec le dossier par défaut
            resolved_custom = custom_path.resolve()
            default_resolved = core.STATION_CFG.data_dir.resolve()
            
            # Si le chemin résolu correspond exactement au dossier par défaut, utiliser le défaut
            # (pour éviter les problèmes de cache et de cohérence)
            if resolved_custom == default_resolved:
                data_dir_to_use = core.STATION_CFG.data_dir
                logger.info(f"Chemin résolu correspond au dossier par défaut pour ML, utilisation du défaut: {data_dir_to_use}")
            else:
                data_dir_to_use = custom_path
                logger.info(f"Utilisation du dossier personnalisé pour ML: {data_dir_to_use}")
        else:
            data_dir_to_use = core.STATION_CFG.data_dir
            logger.debug(f"Utilisation du dossier par défaut pour ML: {data_dir_to_use}")
        
        # Charger les données historiques depuis le dernier fichier GP2 (contient toute la data)
        historical_data = None
        last_gp2_row = None  # Dernière ligne du fichier GP2
        try:
            historical_data = ml_forecast.load_historical_gp2_data(
                data_dir=data_dir_to_use,
                max_files=1  # Uniquement le dernier fichier
            )
            if historical_data is not None:
                logger.info(f"Données historiques chargées: {len(historical_data)} points depuis le dernier fichier GP2")
                # Récupérer la dernière ligne (la plus récente)
                if len(historical_data) > 0:
                    last_gp2_row = historical_data.iloc[-1]
                    # Vérifier que les valeurs sont valides (pas NaN)
                    temp_val = last_gp2_row.get('Tmp(°C)', np.nan)
                    rh_val = last_gp2_row.get('RH(%)', np.nan)
                    vit_val = last_gp2_row.get('Vit(m/s)', np.nan)
                    dir_val = last_gp2_row.get('Dir(°)', np.nan)
                    logger.info(f"Dernière ligne GP2: Temp={temp_val}°C, RH={rh_val}%, Vit={vit_val}m/s, Dir={dir_val}°")
                    # Vérifier si les valeurs sont valides
                    if np.isnan(temp_val) or np.isnan(rh_val):
                        logger.warning(f"⚠️ Valeurs invalides dans la dernière ligne GP2: temp={temp_val}, rh={rh_val}. Vérifiez le parsing du fichier.")
                        # Afficher les colonnes disponibles pour debug
                        logger.debug(f"Colonnes disponibles dans last_gp2_row: {list(last_gp2_row.index)}")
                        logger.debug(f"Valeurs de last_gp2_row: {last_gp2_row.to_dict()}")
        except Exception as e:
            logger.warning(f"Impossible de charger les données historiques: {e}. Continuation sans données historiques.")
        
        # Récupérer le modèle de prévision (défaut: auto)
        forecast_model = request.args.get("model", "auto")
        
        # PRÉDICTION : utiliser les données Open-Meteo à chaque heure comme base
        # Le modèle ML prédit un ajustement par rapport à ces données, pas par rapport à sa propre prédiction précédente
        timeseries = {}
        historical_data_with_predictions = historical_data.copy() if historical_data is not None else None
        
        for h in sorted(hours):  # S'assurer que les heures sont triées
            try:
                # Pour chaque heure, utiliser les données Open-Meteo à cette échéance comme base
                # Cela évite la dérive des prédictions séquentielles
                forecast_field = core.build_openmeteo_forecast_field(
                    core.GRID_CFG, 
                    hour_offset=h, 
                    model=forecast_model
                )
                
                # Pour h=0, on peut optionnellement utiliser la dernière ligne GP2 si disponible
                # Sinon, utiliser directement les données Open-Meteo
                if h == 0 and last_gp2_row is not None:
                    temp_init = float(last_gp2_row.get('Tmp(°C)', np.nan))
                    rh_init = float(last_gp2_row.get('RH(%)', np.nan))
                    vit_init = float(last_gp2_row.get('Vit(m/s)', np.nan))
                    dir_init = float(last_gp2_row.get('Dir(°)', np.nan))
                    
                    # Convertir vitesse/direction en u, v
                    if not np.isnan(vit_init) and not np.isnan(dir_init):
                        dir_rad = np.deg2rad(dir_init)
                        u_init = -vit_init * np.sin(dir_rad)  # Convention météo
                        v_init = -vit_init * np.cos(dir_rad)
                    else:
                        u_init = 0.0
                        v_init = 0.0
                    
                    # Si on a des valeurs valides, créer un champ uniforme avec les valeurs GP2
                    if not np.isnan(temp_init) and not np.isnan(rh_init):
                        ny, nx = core.GRID_CFG.ny, core.GRID_CFG.nx
                        fused_data = {
                            "temp_corr": np.full((ny, nx), temp_init),
                            "rh_corr": np.full((ny, nx), rh_init),
                            "u_corr": np.full((ny, nx), u_init),
                            "v_corr": np.full((ny, nx), v_init)
                        }
                        logger.info(f"Prédiction h=0: utilisation de la dernière ligne GP2 (temp={temp_init:.2f}°C, rh={rh_init:.2f}%, vit={vit_init:.2f}m/s, dir={dir_init:.2f}°)")
                    else:
                        # Fallback: utiliser les données Open-Meteo
                        fused_data = {
                            "temp_corr": forecast_field.temp,
                            "rh_corr": forecast_field.rh,
                            "u_corr": forecast_field.u,
                            "v_corr": forecast_field.v
                        }
                        logger.warning("Valeurs GP2 invalides pour h=0, utilisation des données Open-Meteo")
                else:
                    # Pour h>0, utiliser les données Open-Meteo à cette échéance
                    fused_data = {
                        "temp_corr": forecast_field.temp,
                        "rh_corr": forecast_field.rh,
                        "u_corr": forecast_field.u,
                        "v_corr": forecast_field.v
                    }
                    logger.debug(f"Prédiction h={h}: utilisation des données Open-Meteo à cette échéance")
                
                # Faire la prédiction avec les données historiques enrichies
                predictions = ml_forecast.predict_with_models(
                    fused_data=fused_data,
                    station_lat=station_lat,
                    station_lon=station_lon,
                    grid_config=core.GRID_CFG,
                    hours_ahead=h,
                    model_names=model_names,
                    historical_data=historical_data_with_predictions  # Utiliser les données enrichies
                )
                
                timeseries[h] = predictions
                
                # Ajouter la prédiction précédente aux données historiques pour les features de lag/rolling
                # (mais on n'utilise pas cette prédiction comme base pour la prochaine prédiction)
                if predictions and model_names and len(model_names) > 0:
                    # Utiliser le premier modèle de la liste
                    selected_model = model_names[0]
                    if selected_model in predictions:
                        previous_prediction = predictions[selected_model]
                    elif len(predictions) > 0:
                        # Fallback: utiliser la première prédiction disponible
                        previous_prediction = next(iter(predictions.values()))
                elif predictions:
                    # Pas de modèle spécifié, utiliser la première prédiction disponible
                    previous_prediction = next(iter(predictions.values()))
                else:
                    previous_prediction = None
                
                # Ajouter la prédiction aux données historiques pour enrichir les features de lag/rolling
                if previous_prediction and isinstance(previous_prediction, dict) and 'error' not in previous_prediction:
                    # Créer une nouvelle ligne avec la prédiction
                    pred_dt = datetime.utcnow() + timedelta(hours=h)
                    pred_wind_speed = np.sqrt(previous_prediction.get('u', 0)**2 + previous_prediction.get('v', 0)**2)
                    pred_wind_dir = np.arctan2(previous_prediction.get('u', 0), previous_prediction.get('v', 0)) * 180 / np.pi
                    if pred_wind_dir < 0:
                        pred_wind_dir += 360
                    
                    new_row = pd.DataFrame({
                        'Tmp(°C)': [previous_prediction.get('temp', np.nan)],
                        'RH(%)': [previous_prediction.get('rh', np.nan)],
                        'Vit(m/s)': [pred_wind_speed],
                        'Dir(°)': [pred_wind_dir],
                        'Rad. (W/m²)': [0.0],
                        'Precipitation': [0.0],
                        'precip': [0.0]
                    }, index=[pred_dt])
                    
                    # Ajouter à historical_data_with_predictions pour enrichir les features
                    if historical_data_with_predictions is not None:
                        historical_data_with_predictions = pd.concat([historical_data_with_predictions, new_row]).sort_index()
                        historical_data_with_predictions = historical_data_with_predictions[~historical_data_with_predictions.index.duplicated(keep='last')]
                    else:
                        historical_data_with_predictions = new_row
                
            except Exception as e:
                logger.warning(f"Erreur prédiction ML pour heure {h}: {e}")
                timeseries[h] = {"error": str(e)}
        
        return jsonify({
            "status": "ok",
            "station_position": {
                "lat": float(station_lat),
                "lon": float(station_lon)
            },
            "station_timestamp": datetime.now().isoformat(),
            "timeseries": timeseries,
            "hours": hours
        })
        
    except Exception as e:
        logger.error(f"Erreur dans api_forecast_ml: {e}", exc_info=True)
        return jsonify({
            "error": "Erreur lors de la prédiction ML",
            "message": str(e),
            "status": "error"
        }), 500


@app.route("/api/forecast")
def api_forecast():
    """
    Prévision Open-Meteo spatialisée pour +h heures :
    - interroge Open-Meteo aux 4 coins (séries horaires),
    - prend l'échéance h,
    - interpole bilinéairement (u, v, T, RH) sur toute la grille.
    
    Paramètres:
        hour: Décalage horaire (0-48)
        model: Modèle météorologique (auto, ecmwf_ifs, gfs, gem, icon, metno_nordic, jma_seam)
        global: Si "true", retourne des données globales (grille mondiale)
        lat: Latitude pour une position spécifique (optionnel)
        lon: Longitude pour une position spécifique (optionnel)
    """
    try:
        h = int(request.args.get("hour", 0))
    except Exception:
        h = 0
    h = max(0, min(h, 168))  # bornage simple (0..168 h = 7 jours)
    
    # Récupérer le modèle (défaut: auto)
    model = request.args.get("model", "auto")
    # Valider le modèle (noms corrigés selon les tests)
    valid_models = [
        "auto", "ecmwf_ifs", 
        "gfs_seamless",  # GFS (NOAA) - nom correct
        "gem_global",    # CMC GEM (Canada) - nom correct
        "icon_eu",       # DWD ICON EU (Allemagne) - nom correct
        "icon_global",   # DWD ICON Global - nom correct
    ]
    if model not in valid_models:
        model = "auto"

    # Vérifier si une position spécifique est demandée
    lat_param = request.args.get("lat")
    lon_param = request.args.get("lon")
    
    if lat_param is not None and lon_param is not None:
        # Mode position spécifique : retourner les données pour cette position
        try:
            lat = float(lat_param)
            lon = float(lon_param)
            
            # Récupérer les données Open-Meteo pour cette position
            data = core.fetch_openmeteo_hourly(lat, lon, model=model)
            idx = min(h, len(data.get("time", [])) - 1) if data.get("time") else 0
            idx = max(0, idx)
            
            temp_val = data.get("temperature_2m", [None])[idx] if data.get("temperature_2m") else None
            rh_val = data.get("relative_humidity_2m", [None])[idx] if data.get("relative_humidity_2m") else None
            ws_val = data.get("wind_speed_10m", [None])[idx] if data.get("wind_speed_10m") else None
            wd_val = data.get("wind_direction_10m", [None])[idx] if data.get("wind_direction_10m") else None
            pressure_val = data.get("surface_pressure", [None])[idx] if data.get("surface_pressure") else None
            
            # Convertir vent en u, v
            if ws_val is not None and wd_val is not None:
                u_val, v_val = core.wind_dirspeed_to_uv(ws_val, wd_val)
            else:
                u_val, v_val = None, None
            
            # Créer une petite grille autour de la position pour l'interpolation
            # (nécessaire pour que le frontend puisse utiliser bilinearInterpGlobal)
            grid_size = 0.1  # 0.1° autour de la position
            ny_small = 10
            nx_small = 10
            
            lat_min_small = lat - grid_size / 2
            lat_max_small = lat + grid_size / 2
            lon_min_small = lon - grid_size / 2
            lon_max_small = lon + grid_size / 2
            
            # Créer des grilles avec la valeur constante (ou interpolée si on veut)
            temp_grid = np.full((ny_small, nx_small), temp_val if temp_val is not None else np.nan, dtype=np.float32)
            rh_grid = np.full((ny_small, nx_small), rh_val if rh_val is not None else np.nan, dtype=np.float32)
            u_grid = np.full((ny_small, nx_small), u_val if u_val is not None else np.nan, dtype=np.float32)
            v_grid = np.full((ny_small, nx_small), v_val if v_val is not None else np.nan, dtype=np.float32)
            pressure_grid = np.full((ny_small, nx_small), pressure_val if pressure_val is not None else np.nan, dtype=np.float32)
            
            return jsonify({
                "grid": {
                    "lat_min": float(lat_min_small),
                    "lat_max": float(lat_max_small),
                    "lon_min": float(lon_min_small),
                    "lon_max": float(lon_max_small),
                    "ny": int(ny_small),
                    "nx": int(nx_small),
                },
                "temp": temp_grid.tolist(),
                "rh": rh_grid.tolist(),
                "u": u_grid.tolist(),
                "v": v_grid.tolist(),
                "pressure": pressure_grid.tolist(),
                "hour": int(h),
                "model": model,
            })
        except Exception as e:
            logger.error(f"Erreur récupération données position ({lat_param}, {lon_param}): {e}", exc_info=True)
            return jsonify({
                "error": "Erreur lors de la récupération des données pour cette position",
                "message": str(e),
                "status": "error"
            }), 500

    # Vérifier si mode global
    is_global = request.args.get("global", "false").lower() == "true"
    
    if is_global:
        # Mode global : grille mondiale avec résolution réduite
        return api_forecast_global(h, model)
    else:
        # Mode local : grille Safi
        model_forecast = core.build_openmeteo_forecast_field(core.GRID_CFG, hour_offset=h, model=model)
        ny, nx = core.GRID_CFG.ny, core.GRID_CFG.nx
        return jsonify({
            "grid": {
                "lat_min": float(core.GRID_CFG.lat_min),
                "lat_max": float(core.GRID_CFG.lat_max),
                "lon_min": float(core.GRID_CFG.lon_min),
                "lon_max": float(core.GRID_CFG.lon_max),
                "ny": int(ny),
                "nx": int(nx),
            },
            "temp": model_forecast.temp.tolist(),
            "rh":   model_forecast.rh.tolist(),
            "u":    model_forecast.u.tolist(),
            "v":    model_forecast.v.tolist(),
            "hour": int(h),
            "model": model,
        })


def api_forecast_global(hour_offset: int, model: str):
    """
    Génère une grille globale de données météo pour le globe 3D.
    Utilise une grille de résolution 2° (180x90 points) pour performance.
    """
    # Grille globale : résolution 2° (180 points en longitude, 90 en latitude)
    nx_global = 180  # 360° / 2° = 180
    ny_global = 90   # 180° / 2° = 90
    
    lat_min_global = -90.0
    lat_max_global = 90.0
    lon_min_global = -180.0
    lon_max_global = 180.0
    
    # Créer des grilles pour stocker les données
    temp_grid = np.full((ny_global, nx_global), np.nan, dtype=np.float32)
    rh_grid = np.full((ny_global, nx_global), np.nan, dtype=np.float32)
    u_grid = np.full((ny_global, nx_global), np.nan, dtype=np.float32)
    v_grid = np.full((ny_global, nx_global), np.nan, dtype=np.float32)
    pressure_grid = np.full((ny_global, nx_global), np.nan, dtype=np.float32)
    
    # Échantillonnage : récupérer les données à des points réguliers
    # Pour éviter trop d'appels API, on échantillonne tous les 30° (12 points en lon, 6 en lat = 72 appels max)
    sample_step = 30  # degrés
    sample_lons = np.arange(-180, 181, sample_step)
    sample_lats = np.arange(-90, 91, sample_step)
    
    total_calls = len(sample_lats) * len(sample_lons)
    logger.info(f"Génération grille globale: {len(sample_lats)}x{len(sample_lons)} points d'échantillonnage ({total_calls} appels API)")
    
    # Cache pour éviter les appels API redondants
    cache = {}
    
    try:
        for lat in sample_lats:
            for lon in sample_lons:
                cache_key = f"{lat:.1f}_{lon:.1f}"
                if cache_key not in cache:
                    try:
                        data = core.fetch_openmeteo_hourly(lat, lon, model=model)
                        # Extraire la valeur à l'heure hour_offset
                        idx = min(hour_offset, len(data.get("time", [])) - 1) if data.get("time") else 0
                        idx = max(0, idx)
                        
                        temp_val = data.get("temperature_2m", [None])[idx] if data.get("temperature_2m") else None
                        rh_val = data.get("relative_humidity_2m", [None])[idx] if data.get("relative_humidity_2m") else None
                        ws_val = data.get("wind_speed_10m", [None])[idx] if data.get("wind_speed_10m") else None
                        wd_val = data.get("wind_direction_10m", [None])[idx] if data.get("wind_direction_10m") else None
                        pressure_val = data.get("surface_pressure", [None])[idx] if data.get("surface_pressure") else None
                        
                        # Convertir vent en u, v
                        if ws_val is not None and wd_val is not None:
                            u_val, v_val = core.wind_dirspeed_to_uv(ws_val, wd_val)
                        else:
                            u_val, v_val = None, None
                        
                        cache[cache_key] = {
                            "temp": temp_val,
                            "rh": rh_val,
                            "u": u_val,
                            "v": v_val,
                            "pressure": pressure_val
                        }
                    except Exception as e:
                        logger.warning(f"Erreur pour ({lat}, {lon}): {e}")
                        cache[cache_key] = {"temp": None, "rh": None, "u": None, "v": None, "pressure": None}
                
                # Trouver les indices dans la grille complète
                lat_idx = int((lat - lat_min_global) / 2.0)
                lon_idx = int((lon - lon_min_global) / 2.0)
                lat_idx = max(0, min(ny_global - 1, lat_idx))
                lon_idx = max(0, min(nx_global - 1, lon_idx))
                
                cached = cache[cache_key]
                if cached["temp"] is not None:
                    temp_grid[lat_idx, lon_idx] = cached["temp"]
                if cached["rh"] is not None:
                    rh_grid[lat_idx, lon_idx] = cached["rh"]
                if cached["u"] is not None:
                    u_grid[lat_idx, lon_idx] = cached["u"]
                if cached["v"] is not None:
                    v_grid[lat_idx, lon_idx] = cached["v"]
                if cached["pressure"] is not None:
                    pressure_grid[lat_idx, lon_idx] = cached["pressure"]
        
        # Interpolation pour remplir les cases vides (interpolation simple)
        from scipy.interpolate import griddata
        try:
            # Points connus
            known_lats = []
            known_lons = []
            known_temp = []
            known_rh = []
            known_u = []
            known_v = []
            known_pressure = []
            
            for i in range(ny_global):
                for j in range(nx_global):
                    if not np.isnan(temp_grid[i, j]):
                        known_lats.append(lat_min_global + i * 2.0)
                        known_lons.append(lon_min_global + j * 2.0)
                        known_temp.append(temp_grid[i, j])
                        known_rh.append(rh_grid[i, j])
                        known_u.append(u_grid[i, j])
                        known_v.append(v_grid[i, j])
                        known_pressure.append(pressure_grid[i, j])
            
            if len(known_lats) > 0:
                # Points à interpoler
                grid_lats = np.linspace(lat_min_global, lat_max_global, ny_global)
                grid_lons = np.linspace(lon_min_global, lon_max_global, nx_global)
                grid_lat2d, grid_lon2d = np.meshgrid(grid_lats, grid_lons, indexing='ij')
                
                points = np.column_stack((known_lats, known_lons))
                
                # Interpoler chaque champ
                temp_interp = griddata(points, known_temp, (grid_lat2d, grid_lon2d), method='linear', fill_value=np.nan)
                rh_interp = griddata(points, known_rh, (grid_lat2d, grid_lon2d), method='linear', fill_value=np.nan)
                u_interp = griddata(points, known_u, (grid_lat2d, grid_lon2d), method='linear', fill_value=np.nan)
                v_interp = griddata(points, known_v, (grid_lat2d, grid_lon2d), method='linear', fill_value=np.nan)
                pressure_interp = griddata(points, known_pressure, (grid_lat2d, grid_lon2d), method='linear', fill_value=np.nan)
                
                # Remplacer les NaN par les valeurs interpolées
                temp_grid = np.where(np.isnan(temp_grid), temp_interp, temp_grid)
                rh_grid = np.where(np.isnan(rh_grid), rh_interp, rh_grid)
                u_grid = np.where(np.isnan(u_grid), u_interp, u_grid)
                v_grid = np.where(np.isnan(v_grid), v_interp, v_grid)
                pressure_grid = np.where(np.isnan(pressure_grid), pressure_interp, pressure_grid)
        except ImportError:
            logger.warning("scipy non disponible, utilisation interpolation simple")
            # Fallback: interpolation simple par moyenne des voisins
            for _ in range(5):  # 5 passes d'interpolation
                temp_new = temp_grid.copy()
                rh_new = rh_grid.copy()
                u_new = u_grid.copy()
                v_new = v_grid.copy()
                pressure_new = pressure_grid.copy()
                
                for i in range(1, ny_global - 1):
                    for j in range(1, nx_global - 1):
                        if np.isnan(temp_grid[i, j]):
                            # Moyenne des 4 voisins
                            neighbors_temp = [temp_grid[i-1, j], temp_grid[i+1, j], temp_grid[i, j-1], temp_grid[i, j+1]]
                            neighbors_rh = [rh_grid[i-1, j], rh_grid[i+1, j], rh_grid[i, j-1], rh_grid[i, j+1]]
                            neighbors_u = [u_grid[i-1, j], u_grid[i+1, j], u_grid[i, j-1], u_grid[i, j+1]]
                            neighbors_v = [v_grid[i-1, j], v_grid[i+1, j], v_grid[i, j-1], v_grid[i, j+1]]
                            neighbors_pressure = [pressure_grid[i-1, j], pressure_grid[i+1, j], pressure_grid[i, j-1], pressure_grid[i, j+1]]
                            
                            valid_temp = [v for v in neighbors_temp if not np.isnan(v)]
                            valid_rh = [v for v in neighbors_rh if not np.isnan(v)]
                            valid_u = [v for v in neighbors_u if not np.isnan(v)]
                            valid_v = [v for v in neighbors_v if not np.isnan(v)]
                            valid_pressure = [v for v in neighbors_pressure if not np.isnan(v)]
                            
                            if valid_temp:
                                temp_new[i, j] = np.mean(valid_temp)
                            if valid_rh:
                                rh_new[i, j] = np.mean(valid_rh)
                            if valid_u:
                                u_new[i, j] = np.mean(valid_u)
                            if valid_v:
                                v_new[i, j] = np.mean(valid_v)
                            if valid_pressure:
                                pressure_new[i, j] = np.mean(valid_pressure)
                
                temp_grid = temp_new
                rh_grid = rh_new
                u_grid = u_new
                v_grid = v_new
                pressure_grid = pressure_new
        except Exception as e:
            logger.warning(f"Erreur interpolation: {e}")
        
        # Remplacer les NaN par None (null en JSON) pour éviter les erreurs de parsing
        def replace_nan_with_none(arr):
            """Remplace les NaN par None dans un tableau numpy"""
            result = []
            for row in arr:
                if isinstance(row, np.ndarray):
                    row_list = row.tolist()
                else:
                    row_list = row
                new_row = []
                for v in row_list:
                    if isinstance(v, (float, np.floating)) and (np.isnan(v) or not np.isfinite(v)):
                        new_row.append(None)
                    else:
                        new_row.append(float(v) if isinstance(v, (np.integer, np.floating)) else v)
                result.append(new_row)
            return result
        
        logger.info("Conversion des tableaux numpy en listes Python (remplacement NaN -> null)...")
        temp_list = replace_nan_with_none(temp_grid)
        rh_list = replace_nan_with_none(rh_grid)
        u_list = replace_nan_with_none(u_grid)
        v_list = replace_nan_with_none(v_grid)
        pressure_list = replace_nan_with_none(pressure_grid)
        logger.info("Conversion terminée")
        
        # Créer le dictionnaire de réponse
        response_data = {
            "grid": {
                "lat_min": float(lat_min_global),
                "lat_max": float(lat_max_global),
                "lon_min": float(lon_min_global),
                "lon_max": float(lon_max_global),
                "ny": int(ny_global),
                "nx": int(nx_global),
            },
            "temp": temp_list,
            "rh": rh_list,
            "u": u_list,
            "v": v_list,
            "pressure": pressure_list,
            "hour": int(hour_offset),
            "model": model,
            "station": {
                "name": core.STATION_CFG.name,
                "lat": float(core.STATION_CFG.lat),
                "lon": float(core.STATION_CFG.lon),
            },
        }
        
        # Vérifier que le JSON est valide en le sérialisant d'abord
        try:
            json_str = json.dumps(response_data, allow_nan=False)
            logger.info("JSON valide généré, taille: {} bytes".format(len(json_str)))
        except (ValueError, TypeError) as e:
            logger.error(f"Erreur sérialisation JSON: {e}")
            # Essayer de nettoyer les valeurs problématiques
            def clean_value(v):
                if isinstance(v, (list, tuple)):
                    return [clean_value(item) for item in v]
                elif isinstance(v, dict):
                    return {k: clean_value(val) for k, val in v.items()}
                elif isinstance(v, (float, np.floating)):
                    if np.isnan(v) or not np.isfinite(v):
                        return None
                    return float(v)
                elif isinstance(v, (int, np.integer)):
                    return int(v)
                else:
                    return v
            
            response_data = clean_value(response_data)
            json_str = json.dumps(response_data, allow_nan=False)
            logger.info("JSON nettoyé et valide, taille: {} bytes".format(len(json_str)))
        
        # Créer une réponse avec Content-Length pour permettre le suivi de progression
        # Encoder en bytes pour obtenir la taille réelle
        json_bytes = json_str.encode('utf-8')
        content_length = len(json_bytes)
        
        response = app.response_class(
            response=json_bytes,
            status=200,
            mimetype='application/json; charset=utf-8'
        )
        response.headers['Content-Length'] = str(content_length)
        # Désactiver la compression pour que Content-Length soit fiable
        response.headers['Content-Encoding'] = 'identity'
        logger.info(f"Réponse créée avec Content-Length: {content_length} bytes")
        return response
    except Exception as e:
        logger.error(f"Erreur génération grille globale: {e}", exc_info=True)
        return jsonify({
            "error": "Erreur lors de la génération de la grille globale",
            "message": str(e),
            "status": "error"
        }), 500




@app.route("/")
def index():
    return render_template("index.html")


@app.route("/diagnostics")
def diagnostics_page():
    """Page HTML de diagnostics"""
    return render_template("diagnostics.html")


@app.route("/api/health")
def api_health():
    """Endpoint de santé - vérifie que le serveur fonctionne"""
    response = jsonify({
        "status": "ok",
        "timestamp": datetime.now().isoformat(),
        "message": "Serveur opérationnel"
    })
    # S'assurer que les headers CORS sont présents même si flask-cors n'est pas installé
    response.headers.add('Access-Control-Allow-Origin', '*')
    return response


# Variable globale pour stocker le data_dir sélectionné (utilisée par l'interface Windy)
_current_data_dir = None

@app.route("/api/data-dir", methods=["GET", "POST"])
def api_data_dir():
    """
    Endpoint pour obtenir ou définir le dossier de données actuel.
    Utilisé par l'interface Windy pour synchroniser avec le dashboard.
    """
    global _current_data_dir
    
    if request.method == "POST":
        # Définir le data_dir
        data = request.get_json() or {}
        new_data_dir = data.get("data_dir", None)
        _current_data_dir = new_data_dir
        logger.info(f"Data dir mis à jour via API: {_current_data_dir}")
        return jsonify({
            "status": "ok",
            "data_dir": _current_data_dir
        })
    else:
        # Obtenir le data_dir actuel
        return jsonify({
            "status": "ok",
            "data_dir": _current_data_dir,
            "default_data_dir": str(core.STATION_CFG.data_dir)
        })


@app.route("/api/dashboard/data")
def api_dashboard_data():
    """
    Charge les 10 dernières mesures depuis le fichier GP2 le plus récent.
    Utilise un cache pour des réponses instantanées.
    Retourne les données dans un format adapté au dashboard.
    
    Paramètres:
        data_dir: (optionnel) Chemin du dossier de données personnalisé. 
                  Si non fourni, utilise le dossier par défaut (core.STATION_CFG.data_dir).
        target_date: (optionnel) Date cible pour le mode historique (format: YYYY-MM-DD ou ISO timestamp).
                     Si non fourni, retourne les 10 dernières mesures (mode temps réel).
        target_hour: (optionnel) Heure cible pour le mode historique (format: HH:MM).
                     Utilisé uniquement si target_date est fourni.
    """
    global _dashboard_cache
    
    try:
        import re
        
        # Récupérer le dossier de données (optionnel)
        custom_data_dir = request.args.get("data_dir", None)
        
        # Utiliser le dossier personnalisé si fourni, sinon le dossier par défaut
        if custom_data_dir:
            # Nettoyer le chemin (enlever les espaces, etc.)
            custom_data_dir = custom_data_dir.strip()
            
            # IMPORTANT: Détecter si c'est un chemin absolu ou juste un nom de dossier
            import os
            
            # Détecter si c'est déjà un chemin absolu (Windows ou Unix)
            is_absolute_input = (
                len(custom_data_dir) >= 2 and custom_data_dir[1] == ':' or  # Windows: C:\ ou D:\
                custom_data_dir.startswith('/') or  # Unix: /path
                custom_data_dir.startswith('\\') or  # Windows UNC: \\server\share
                custom_data_dir.startswith('\\\\?\\')  # Windows long path: \\?\C:\
            )
            
            if is_absolute_input:
                # C'est déjà un chemin absolu - utiliser directement
                custom_path = Path(custom_data_dir)
                try:
                    custom_path = custom_path.resolve()
                except Exception:
                    pass
            else:
                # C'est juste un nom de dossier - chercher dans plusieurs emplacements
                # Liste des emplacements à chercher (par ordre de priorité)
                search_locations = []
                
                # 1. Répertoire de travail courant
                cwd = Path(os.getcwd())
                search_locations.append(("Répertoire de travail courant", cwd))
                
                # 2. Répertoire du serveur
                server_dir = Path(__file__).parent
                search_locations.append(("Répertoire du serveur", server_dir))
                
                # 3. Répertoire parent du serveur
                parent_dir = server_dir.parent
                search_locations.append(("Répertoire parent du serveur", parent_dir))
                
                # 4. Répertoire parent du parent (2 niveaux au-dessus)
                if parent_dir.parent.exists():
                    search_locations.append(("2 niveaux au-dessus du serveur", parent_dir.parent))
                
                # 5. Répertoire utilisateur (Documents, Desktop, etc.)
                user_home = Path.home()
                search_locations.append(("Répertoire utilisateur", user_home))
                if (user_home / "Documents").exists():
                    search_locations.append(("Documents utilisateur", user_home / "Documents"))
                if (user_home / "Desktop").exists():
                    search_locations.append(("Desktop utilisateur", user_home / "Desktop"))
                if (user_home / "Downloads").exists():
                    search_locations.append(("Downloads utilisateur", user_home / "Downloads"))
                
                # 6. Tous les lecteurs Windows (C:\, D:\, etc.)
                if os.name == 'nt':  # Windows
                    import string
                    for drive in string.ascii_uppercase:
                        drive_path = Path(f"{drive}:\\")
                        if drive_path.exists():
                            search_locations.append((f"Racine du lecteur {drive}:", drive_path))
                
                found = False
                for location_name, base_path in search_locations:
                    test_path = base_path / custom_data_dir
                    if test_path.exists() and test_path.is_dir():
                        custom_path = test_path.resolve()
                        found = True
                        break
                
                if not found:
                    # Aucun dossier trouvé - utiliser os.path.abspath() comme fallback
                    absolute_path_str = os.path.abspath(custom_data_dir)
                    custom_path = Path(absolute_path_str)
            
            if not custom_path.exists() or not custom_path.is_dir():
                logger.error("❌ DOSSIER PERSONNALISÉ NON TROUVÉ")
                logger.error(f"   Chemin demandé: {custom_data_dir}")
                logger.error(f"   Chemin absolu tenté: {custom_path.resolve()}")
                # Lister les dossiers possibles pour aider au débogage
                server_dir = Path(__file__).parent
                logger.error(f"   Répertoire du serveur: {server_dir}")
                if server_dir.exists():
                    try:
                        dirs_in_server = [d.name for d in server_dir.iterdir() if d.is_dir()]
                        logger.error(f"   Dossiers dans le répertoire du serveur: {dirs_in_server}")
                    except Exception as e:
                        logger.error(f"   Impossible de lister les dossiers: {e}")
                return jsonify({
                    "status": "no_data",
                    "error": "Dossier de données personnalisé non trouvé",
                    "data_dir": str(custom_path),
                    "data_dir_requested": custom_data_dir,
                    "data_dir_absolute": str(custom_path.resolve()),
                    "message": f"Le dossier '{custom_data_dir}' n'a pas pu être trouvé. Vérifiez le chemin.",
                    "data": [],
                    "wind_rose": None,
                    "metrics": None
                }), 200
            
            # Résoudre le chemin pour comparer avec le dossier par défaut
            resolved_custom = custom_path.resolve()
            
            # Vérifier si le dossier par défaut existe
            default_exists = core.STATION_CFG.data_dir.exists()
            if default_exists:
                default_resolved = core.STATION_CFG.data_dir.resolve()
                # Si le chemin résolu correspond exactement au dossier par défaut, utiliser le défaut
                if resolved_custom == default_resolved:
                    data_dir = core.STATION_CFG.data_dir
                else:
                    # Utiliser le dossier personnalisé - c'est différent du défaut
                    data_dir = custom_path
            else:
                # Le dossier par défaut n'existe pas, utiliser le dossier personnalisé
                data_dir = custom_path
        else:
            # Dossier par défaut - s'assurer qu'il existe
            data_dir = core.STATION_CFG.data_dir
            if not data_dir.exists():
                # Essayer de créer le dossier s'il n'existe pas
                try:
                    data_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(f"Dossier data par défaut créé à la volée: {data_dir}")
                except Exception as e:
                    logger.error(f"Impossible de créer le dossier data par défaut: {e}")
                    return jsonify({
                        "status": "no_data",
                        "error": "Dossier de données par défaut non trouvé et impossible à créer",
                        "data_dir": str(data_dir),
                        "data_dir_absolute": str(data_dir.resolve()),
                        "message": "Le dossier par défaut n'existe pas et n'a pas pu être créé. Veuillez fournir un dossier personnalisé via le paramètre data_dir.",
                        "data": None,
                        "wind_rose": None,
                        "metrics": None
                    }), 200
            logger.debug(f"Utilisation du dossier par défaut: {data_dir}")
        
        # Vérifier le cache d'abord (fonctionne maintenant pour tous les dossiers)
        # Utiliser le chemin absolu comme clé de cache
        cache_key = str(data_dir.resolve())
        
        # Vérifier si on a un cache valide pour ce dossier
        if cache_key in _dashboard_cache:
            cache_entry = _dashboard_cache[cache_key]
            cache_age = (datetime.now() - cache_entry["timestamp"]).total_seconds()
            
            # Vérifier aussi si le dernier fichier a changé (invalidation intelligente)
            last_file_mtime = cache_entry.get("last_file_mtime", 0)
            cache_valid = True
            
            # Vérifier si le dernier fichier a changé (vérification rapide)
            try:
                # Chercher rapidement le dernier fichier pour vérifier son mtime
                all_files = list(data_dir.glob("GP2_*.txt"))
                if not all_files:
                    station_name = core.STATION_CFG.name
                    all_files = list(data_dir.glob(f"{station_name}_*.txt"))
                
                if all_files:
                    # Trouver le fichier le plus récent par modification time
                    latest_file_by_mtime = max(all_files, key=lambda f: f.stat().st_mtime)
                    current_mtime = latest_file_by_mtime.stat().st_mtime
                    
                    # Si le fichier a changé, invalider le cache
                    if current_mtime != last_file_mtime:
                        cache_valid = False
                else:
                    # Pas de fichiers, invalider le cache
                    cache_valid = False
            except Exception:
                pass
            
            # Si le cache est valide et récent, l'utiliser
            if cache_valid and cache_age < _dashboard_cache_ttl:
                return jsonify(cache_entry["data"])
            else:
                # Cache expiré ou fichier modifié, le supprimer
                del _dashboard_cache[cache_key]
        
        if not data_dir.exists():
            logger.error(f"Dossier de données non trouvé: {data_dir}")
            # Retourner une réponse avec status "no_data" plutôt qu'une erreur 404
            # pour permettre au frontend de gérer gracieusement l'absence de données
            return jsonify({
                "status": "no_data",
                "error": "Dossier de données non trouvé",
                "data_dir": str(data_dir),
                "data_dir_absolute": str(data_dir.resolve()),
                "data": [],
                "wind_rose": None,
                "metrics": None
            }), 200
        
        # Pattern pour extraire le timestamp du nom de fichier
        fname_regex = re.compile(r"GP2_(\d{2}-\d{2}-\d{2})_(\d{2}-\d{2}-\d{2})\.txt$")
        
        def extract_ts_from_filename(fname: str):
            m = fname_regex.search(fname)
            if not m:
                return None
            date_str, time_str = m.group(1), m.group(2)
            try:
                return datetime.strptime(f"{date_str}_{time_str}", "%d-%m-%y_%H-%M-%S")
            except:
                return None
        
        # Trouver le fichier GP2 le plus récent
        files_with_ts = []
        
        # Essayer d'abord avec le pattern strict GP2_*.txt
        all_files = list(data_dir.glob("GP2_*.txt"))
        
        # Si aucun fichier trouvé, essayer aussi avec le nom de la station depuis STATION_CFG
        if not all_files:
            station_name = core.STATION_CFG.name
            all_files = list(data_dir.glob(f"{station_name}_*.txt"))
        
        # Lister tous les fichiers .txt pour débogage (seulement si erreur)
        all_txt_files = list(data_dir.glob("*.txt"))
        
        # Valider les fichiers trouvés
        for f in all_files:
            if not f.is_file():
                continue
            ts = extract_ts_from_filename(f.name)
            if ts is not None:
                files_with_ts.append((ts, f))
        
        if not files_with_ts:
            # Lister tous les fichiers pour aider au débogage
            all_files_in_dir = [f for f in data_dir.iterdir() if f.is_file()]
            logger.error(f"Aucun fichier GP2 valide trouvé dans {data_dir}")
            logger.error(f"Chemin absolu: {data_dir.resolve()}")
            logger.error(f"Fichiers présents dans le dossier: {[f.name for f in all_files_in_dir]}")
            logger.error(f"Fichiers .txt trouvés: {[f.name for f in all_txt_files] if all_txt_files else 'Aucun'}")
            # Retourner une réponse avec status "no_data" plutôt qu'une erreur 404
            # pour permettre au frontend de gérer gracieusement l'absence de données
            return jsonify({
                "status": "no_data",
                "error": "Aucun fichier GP2 valide trouvé",
                "data_dir": str(data_dir),
                "data_dir_absolute": str(data_dir.resolve()),
                "files_in_directory": [f.name for f in all_files_in_dir],
                "txt_files": [f.name for f in all_txt_files] if all_txt_files else [],
                "pattern_searched": ["GP2_*.txt", f"{core.STATION_CFG.name}_*.txt"],
                "data": [],
                "wind_rose": None,
                "metrics": None
            }), 200
        
        # Récupérer les paramètres de date pour le mode historique
        target_date_str = request.args.get("target_date", None)
        target_hour_str = request.args.get("target_hour", None)
        
        # Trier par timestamp (plus récent en premier) et prendre le dernier fichier
        files_with_ts.sort(key=lambda x: x[0], reverse=True)
        
        latest_file = files_with_ts[0][1]
        # Récupérer le mtime du fichier pour l'invalidation intelligente du cache
        latest_file_mtime = latest_file.stat().st_mtime
        
        # Déterminer le mode : historique ou temps réel
        is_historical_mode = target_date_str is not None
        
        # Parser la date cible si fournie
        target_timestamp = None
        if is_historical_mode:
            try:
                # Essayer de parser la date (format YYYY-MM-DD ou ISO)
                if 'T' in target_date_str or ' ' in target_date_str:
                    # Format ISO ou avec heure
                    from datetime import datetime as dt_parse
                    target_timestamp = dt_parse.fromisoformat(target_date_str.replace('Z', '+00:00'))
                else:
                    # Format YYYY-MM-DD
                    from datetime import datetime as dt_parse
                    target_timestamp = dt_parse.strptime(target_date_str, "%Y-%m-%d")
                
                # Ajouter l'heure si fournie
                if target_hour_str:
                    try:
                        hour_parts = target_hour_str.split(':')
                        if len(hour_parts) >= 2:
                            target_timestamp = target_timestamp.replace(
                                hour=int(hour_parts[0]),
                                minute=int(hour_parts[1]),
                                second=0
                            )
                    except:
                        pass
                
                logger.info(f"Mode historique activé - Date cible: {target_timestamp}")
            except Exception as e:
                logger.warning(f"Erreur parsing date cible: {e}, passage en mode temps réel")
                is_historical_mode = False
        
        valid_lines = []
        try:
            if is_historical_mode:
                # Mode historique : utiliser la même méthode que read_data_file pour lire le fichier
                logger.info("=" * 80)
                try:
                    # Lire le fichier avec pandas comme dans read_data_file
                    column_names_7 = ['Date', 'Heure', 'Power', 'Speed#@1m', 'Dir', 'RH', 'AirTemp']
                    df = pd.read_csv(
                        latest_file, 
                        sep=r'\s+', 
                        skiprows=1, 
                        encoding='utf-8', 
                        engine='python',
                        names=column_names_7,
                        header=None
                    )
                    
                    # Combiner Date et Heure en un seul Timestamp
                    df['Timestamp'] = df['Date'].astype(str) + ' ' + df['Heure'].astype(str)
                    
                    # Convertir les valeurs numériques (remplacer les virgules par des points)
                    numeric_cols = ['Power', 'Speed#@1m', 'Dir', 'RH', 'AirTemp']
                    for col in numeric_cols:
                        if col in df.columns:
                            df[col] = pd.to_numeric(
                                df[col].astype(str).str.replace(',', '.'), 
                                errors='coerce'
                            )
                    
                    # Convertir la colonne Timestamp en datetime
                    df['Timestamp'] = pd.to_datetime(df['Timestamp'], format='%d/%m/%Y %H:%M:%S', errors='coerce', dayfirst=True)
                    
                    # Supprimer les lignes avec timestamp invalide
                    df = df.dropna(subset=['Timestamp'])
                    
                    if len(df) == 0:
                        valid_lines = []
                    else:
                        # Filtrer pour ne garder que les données >= à la date cible
                        df_filtered = df[df['Timestamp'] >= target_timestamp]
                        
                        if len(df_filtered) == 0:
                            valid_lines = []
                        else:
                            # Trier par timestamp croissant (chronologique)
                            df_filtered = df_filtered.sort_values('Timestamp')
                            
                            # Prendre les 10 premières mesures disponibles à partir de la date cible
                            df_selected = df_filtered.head(10)
                            
                            # Convertir en format de réponse
                            for idx, (original_idx, row) in enumerate(df_selected.iterrows(), start=1):
                                # Vérifier que toutes les valeurs sont valides
                                power = row.get('Power')
                                speed = row.get('Speed#@1m')
                                direction = row.get('Dir')
                                rh = row.get('RH')
                                temp = row.get('AirTemp')
                                
                                if pd.notna(power) and pd.notna(speed) and pd.notna(direction) and pd.notna(rh) and pd.notna(temp):
                                    timestamp = row['Timestamp']
                                    valid_lines.append({
                                        "timestamp": timestamp.isoformat(),
                                        "date": timestamp.strftime("%d/%m/%Y"),
                                        "time": timestamp.strftime("%H:%M:%S"),
                                        "power": float(power),
                                        "vitesse": float(speed),
                                        "direction": float(direction),
                                        "humidite": float(rh),
                                        "temperature": float(temp),
                                    })
                            
                
                except Exception as e:
                    logger.error(f"❌ Erreur lors de la lecture du fichier pour le mode historique: {e}", exc_info=True)
                    valid_lines = []
            else:
                # Mode temps réel : lire seulement les 200 dernières lignes (optimisation)
                # Lire le fichier en mode binaire pour une lecture efficace depuis la fin
                with latest_file.open("rb") as f:
                    # Lire les 50 derniers KB (suffisant pour ~200 lignes)
                    try:
                        f.seek(-50 * 1024, 2)  # 2 = fin du fichier
                    except OSError:
                        # Fichier trop petit, lire depuis le début
                        f.seek(0)
                    
                    # Lire les lignes
                    raw_data = f.read()
                    lines = raw_data.decode("utf-8", errors="ignore").splitlines()
                    # Prendre seulement les 200 dernières lignes
                    lines = lines[-200:]
                
                # Parser les lignes de données (en commençant par la fin)
                lines_processed = 0
                lines_valid = 0
                for line in reversed(lines):  # Commencer par la fin
                    lines_processed += 1
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Découpage sur espaces/tabs
                    parts = re.split(r"\s+", line)
                    if len(parts) < 7:
                        continue
                    
                    # Tester si les deux premières colonnes sont une date+heure valide
                    date_str = parts[0]
                    time_str = parts[1]
                    dt_str = f"{date_str} {time_str}"
                    
                    try:
                        timestamp = datetime.strptime(dt_str, "%d/%m/%Y %H:%M:%S")
                    except ValueError:
                        continue
                    
                    # Parser les valeurs
                    def ffloat(s: str) -> float:
                        try:
                            return float(s.replace(",", "."))
                        except:
                            return None
                    
                    power = ffloat(parts[2])
                    speed = ffloat(parts[3])
                    direction = ffloat(parts[4])
                    rh = ffloat(parts[5])
                    temp = ffloat(parts[6])
                    
                    # Vérifier que toutes les valeurs sont valides
                    if all(v is not None for v in [power, speed, direction, rh, temp]):
                        lines_valid += 1
                        valid_lines.append({
                            "timestamp": timestamp.isoformat(),
                            "date": timestamp.strftime("%d/%m/%Y"),
                            "time": timestamp.strftime("%H:%M:%S"),
                            "power": power,
                            "vitesse": speed,
                            "direction": direction,
                            "humidite": rh,
                            "temperature": temp,
                        })
                        
                        # Arrêter après avoir trouvé 10 lignes valides
                        if len(valid_lines) >= 10:
                            break
                
        except Exception as e:
            logger.error(f"Erreur lors du chargement de {latest_file.name}: {e}", exc_info=True)
            return jsonify({
                "status": "no_data",
                "error": "Erreur lors du chargement du fichier",
                "message": str(e),
                "data_dir": str(data_dir),
                "data_dir_absolute": str(data_dir.resolve()) if data_dir.exists() else "N/A",
                "data": [],
                "wind_rose": None,
                "metrics": None
            }), 200
        
        # Vérifier qu'on a des données valides
        if not valid_lines:
            return jsonify({
                "status": "no_data",
                "error": "Aucune donnée valide trouvée dans le fichier",
                "data_dir": str(data_dir),
                "data_dir_absolute": str(data_dir.resolve()) if data_dir.exists() else "N/A",
                "data": [],
                "wind_rose": None,
                "metrics": None
            }), 200
        
        # En mode historique, les données sont déjà triées en ordre croissant
        # En mode temps réel, inverser pour avoir les plus anciennes en premier
        if not is_historical_mode:
            valid_lines.reverse()
        
        # Préparer la réponse avec vérifications de sécurité
        response_data = {
            "status": "ok",
            "data": valid_lines,
            "count": len(valid_lines),
            "data_dir": str(data_dir),
            "first_timestamp": valid_lines[0]["timestamp"] if len(valid_lines) > 0 else None,
            "last_timestamp": valid_lines[-1]["timestamp"] if len(valid_lines) > 0 else None,
        }
        
        # Mettre en cache pour tous les dossiers (par défaut et personnalisés)
        # Utiliser le chemin absolu comme clé avec gestion d'erreur
        try:
            cache_key = str(data_dir.resolve())
        except Exception as e:
            cache_key = str(data_dir)
        
        # Nettoyer les anciens caches (garder seulement les 10 plus récents pour éviter la surcharge mémoire)
        if len(_dashboard_cache) > 10:
            # Supprimer les caches les plus anciens
            sorted_caches = sorted(_dashboard_cache.items(), key=lambda x: x[1]["timestamp"])
            caches_to_remove = len(_dashboard_cache) - 10
            for i in range(caches_to_remove):
                old_key = sorted_caches[i][0]
                del _dashboard_cache[old_key]
        
        # Mettre à jour le cache avec les nouvelles données
        # Vérifier que latest_file_mtime est défini
        try:
            _dashboard_cache[cache_key] = {
                "data": response_data.copy(),
                "timestamp": datetime.now(),
                "last_file_mtime": latest_file_mtime,
                "data_dir": str(data_dir)
            }
        except NameError:
            # latest_file_mtime n'est pas défini (ne devrait pas arriver, mais sécurité)
            _dashboard_cache[cache_key] = {
                "data": response_data.copy(),
                "timestamp": datetime.now(),
                "last_file_mtime": 0,
                "data_dir": str(data_dir)
            }
        
        return jsonify(response_data)
        
    except Exception as e:
        logger.error(f"Erreur dans api_dashboard_data: {e}", exc_info=True)
        return jsonify({
            "error": "Erreur lors du chargement des données",
            "message": str(e),
            "status": "error"
        }), 500


@app.route("/api/test/openmeteo")
def api_test_openmeteo():
    """
    Teste la connexion à l'API Open-Meteo avec différents modèles.
    Retourne le statut de chaque modèle.
    """
    test_lat = 32.23  # Safi
    test_lon = -9.25
    models = ["auto", "ecmwf_ifs", "gfs", "gem", "icon", "metno_nordic", "jma_seam"]
    
    results = {
        "test_location": {"lat": test_lat, "lon": test_lon},
        "timestamp": datetime.now().isoformat(),
        "models": {}
    }
    
    for model in models:
        try:
            logger.info(f"Test du modèle: {model}")
            start_time = datetime.now()
            
            # Test avec fetch_openmeteo_hourly
            data = core.fetch_openmeteo_hourly(test_lat, test_lon, model=model)
            
            elapsed = (datetime.now() - start_time).total_seconds()
            
            # Vérifier que les données sont présentes
            has_data = (
                data.get("time") and len(data.get("time", [])) > 0 and
                data.get("temperature_2m") and len(data.get("temperature_2m", [])) > 0
            )
            
            results["models"][model] = {
                "status": "ok" if has_data else "no_data",
                "response_time_seconds": round(elapsed, 2),
                "data_points": len(data.get("time", [])),
                "sample_temperature": data.get("temperature_2m", [None])[0] if data.get("temperature_2m") else None,
                "error": None
            }
            
            logger.info(f"✓ Modèle {model}: OK ({elapsed:.2f}s)")
            
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds() if 'start_time' in locals() else 0
            results["models"][model] = {
                "status": "error",
                "response_time_seconds": round(elapsed, 2),
                "error": str(e)
            }
            logger.error(f"✗ Modèle {model}: ERREUR - {e}")
    
    return jsonify(results)


@app.route("/api/test/forecast")
def api_test_forecast():
    """
    Teste l'endpoint de prévision avec différents modèles et échéances.
    """
    test_cases = [
        {"hour": 0, "model": "auto"},
        {"hour": 12, "model": "ecmwf_ifs"},
        {"hour": 24, "model": "gfs"},
    ]
    
    results = {
        "timestamp": datetime.now().isoformat(),
        "tests": []
    }
    
    for test_case in test_cases:
        try:
            logger.info(f"Test prévision: hour={test_case['hour']}, model={test_case['model']}")
            start_time = datetime.now()
            
            forecast = core.build_openmeteo_forecast_field(
                core.GRID_CFG,
                hour_offset=test_case["hour"],
                model=test_case["model"]
            )
            
            elapsed = (datetime.now() - start_time).total_seconds()
            
            # Vérifier les données
            has_data = (
                forecast.temp is not None and
                forecast.u is not None and
                forecast.v is not None
            )
            
            results["tests"].append({
                "hour": test_case["hour"],
                "model": test_case["model"],
                "status": "ok" if has_data else "no_data",
                "response_time_seconds": round(elapsed, 2),
                "grid_size": f"{core.GRID_CFG.ny}x{core.GRID_CFG.nx}",
                "temp_range": [
                    float(np.nanmin(forecast.temp)),
                    float(np.nanmax(forecast.temp))
                ] if has_data else None,
                "error": None
            })
            
            logger.info(f"✓ Prévision hour={test_case['hour']}, model={test_case['model']}: OK")
            
        except Exception as e:
            elapsed = (datetime.now() - start_time).total_seconds() if 'start_time' in locals() else 0
            results["tests"].append({
                "hour": test_case["hour"],
                "model": test_case["model"],
                "status": "error",
                "response_time_seconds": round(elapsed, 2),
                "error": str(e)
            })
            logger.error(f"✗ Prévision hour={test_case['hour']}, model={test_case['model']}: ERREUR - {e}")
    
    return jsonify(results)


@app.route("/api/diagnostics")
def api_diagnostics():
    """
    Page de diagnostic complète - teste tous les composants.
    """
    diagnostics = {
        "timestamp": datetime.now().isoformat(),
        "server": {
            "status": "ok",
            "python_version": __import__("sys").version.split()[0]
        },
        "grid_config": {
            "nx": core.GRID_CFG.nx,
            "ny": core.GRID_CFG.ny,
            "lat_min": core.GRID_CFG.lat_min,
            "lat_max": core.GRID_CFG.lat_max,
            "lon_min": core.GRID_CFG.lon_min,
            "lon_max": core.GRID_CFG.lon_max,
        },
        "station_config": {
            "name": core.STATION_CFG.name,
            "lat": core.STATION_CFG.lat,
            "lon": core.STATION_CFG.lon,
        },
        "api_tests": {}
    }
    
    # Test Open-Meteo
    try:
        logger.info("Démarrage des tests API...")
        test_result = core.fetch_openmeteo_hourly(32.23, -9.25, model="auto")
        diagnostics["api_tests"]["openmeteo_basic"] = {
            "status": "ok",
            "data_points": len(test_result.get("time", [])),
            "sample_time": test_result.get("time", [None])[0]
        }
    except Exception as e:
        diagnostics["api_tests"]["openmeteo_basic"] = {
            "status": "error",
            "error": str(e)
        }
    
    return jsonify(diagnostics)


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """
    Endpoint pour le chatbot météorologique.
    Accepte une question et retourne une réponse basée sur les données GP2 et Open Meteo.
    Supporte la gestion des conversations avec conversation_id.
    """
    try:
        logger.info("📨 Requête chatbot reçue")
        data = request.get_json()
        question = data.get("question", "")
        conversation_id = data.get("conversation_id", None)
        new_conversation = data.get("new_conversation", False)
        
        logger.info(f"   Question: {question[:100]}...")
        logger.info(f"   Conversation ID: {conversation_id}")
        logger.info(f"   Nouvelle conversation: {new_conversation}")
        
        if not question:
            logger.warning("❌ Question manquante dans la requête")
            return jsonify({
                "error": "Question manquante",
                "status": "error"
            }), 400
        
        # Récupérer le dossier de données (depuis la variable globale)
        global _current_data_dir
        custom_data_dir = _current_data_dir
        
        # Déterminer le data_dir à utiliser
        data_dir_to_use = None
        if custom_data_dir:
            # Convertir en Path (essayer d'abord comme chemin absolu, puis relatif)
            custom_path = Path(custom_data_dir)
            
            # Si le chemin n'est pas absolu et n'existe pas, essayer depuis le répertoire parent
            if not custom_path.is_absolute() and not custom_path.exists():
                server_dir = Path(__file__).parent
                custom_path = server_dir / custom_data_dir
            
            # Vérifier que le dossier existe
            if custom_path.exists() and custom_path.is_dir():
                # Résoudre le chemin pour comparer avec le dossier par défaut
                resolved_custom = custom_path.resolve()
                default_resolved = core.STATION_CFG.data_dir.resolve()
                
                # Si le chemin résolu correspond exactement au dossier par défaut, utiliser le défaut
                if resolved_custom != default_resolved:
                    data_dir_to_use = custom_path
                    logger.info(f"Chatbot utilise le dossier personnalisé: {data_dir_to_use}")
        
        # Vérifier si le chatbot est disponible
        # Note: Le chatbot peut fonctionner en mode dégradé même sans clé API
        # mais avec des capacités limitées
        chatbot_available = chatbot_windy.CEREBRAS_AVAILABLE
        logger.info(f"🤖 Chatbot disponible: {chatbot_available}")
        if not chatbot_available:
            logger.warning("⚠️  Chatbot utilisé en mode dégradé (clé API Cerebras manquante)")
        
        # Gérer les conversations
        try:
            chatbot = chatbot_windy.get_chatbot()
            logger.info("✅ Chatbot initialisé avec succès")
        except Exception as e:
            logger.error(f"❌ Erreur lors de l'initialisation du chatbot: {e}", exc_info=True)
            return jsonify({
                "error": "Erreur lors de l'initialisation du chatbot",
                "message": str(e),
                "status": "error"
            }), 500
        
        # Nouvelle conversation demandée
        if new_conversation:
            chatbot.new_conversation()
        # Charger une conversation existante
        elif conversation_id:
            chatbot.load_conversation(conversation_id)
        
        # Récupérer les données station actuelles
        # Utiliser le cache pour éviter de recalculer si les données sont récentes
        try:
            station_data = compute_fields(use_cache=True, data_dir=data_dir_to_use)
        except Exception as e:
            logger.warning(f"Impossible de récupérer les données station: {e}")
            station_data = {}
        
        # Toujours essayer de récupérer les données de prévision (temps réel = heure 0)
        # Récupérer plusieurs échéances pour permettre le calcul de moyennes
        forecast_data = None
        try:
            hour = int(data.get("forecast_hour", 0)) if data.get("include_forecast", False) else 0
            model = data.get("forecast_model", "auto") if data.get("include_forecast", False) else "auto"
            
            # Récupérer les données de prévision pour toute la semaine (7 jours)
            # Échéances: 0h, 24h, 48h, 72h, 96h, 120h, 144h, 168h
            forecast_hours = [0, 24, 48, 72, 96, 120, 144, 168] if not data.get("include_forecast", False) else [hour]
            forecast_temps = []
            forecast_temps_at_station = []
            
            # Position de la station GP2
            station_lat = core.STATION_CFG.lat
            station_lon = core.STATION_CFG.lon
            
            for h in forecast_hours:
                try:
                    forecast_field = core.build_openmeteo_forecast_field(core.GRID_CFG, hour_offset=h, model=model)
                    
                    # Calculer la plage de température sur la grille
                    temp_min = float(np.nanmin(forecast_field.temp)) if forecast_field.temp is not None else None
                    temp_max = float(np.nanmax(forecast_field.temp)) if forecast_field.temp is not None else None
                    temp_mean = float(np.nanmean(forecast_field.temp)) if forecast_field.temp is not None else None
                    
                    # Calculer la plage d'humidité relative sur la grille
                    rh_min = float(np.nanmin(forecast_field.rh)) if forecast_field.rh is not None else None
                    rh_max = float(np.nanmax(forecast_field.rh)) if forecast_field.rh is not None else None
                    rh_mean = float(np.nanmean(forecast_field.rh)) if forecast_field.rh is not None else None
                    
                    # Conversion lat/lon en indices de grille (réutilisable pour temp et rh)
                    i_norm = (station_lat - core.GRID_CFG.lat_min) / (core.GRID_CFG.lat_max - core.GRID_CFG.lat_min + 1e-12)
                    j_norm = (station_lon - core.GRID_CFG.lon_min) / (core.GRID_CFG.lon_max - core.GRID_CFG.lon_min + 1e-12)
                    
                    i_float = i_norm * (core.GRID_CFG.ny - 1)
                    j_float = j_norm * (core.GRID_CFG.nx - 1)
                    
                    i0 = int(np.clip(np.floor(i_float), 0, core.GRID_CFG.ny - 1))
                    j0 = int(np.clip(np.floor(j_float), 0, core.GRID_CFG.nx - 1))
                    i1 = int(np.clip(i0 + 1, 0, core.GRID_CFG.ny - 1))
                    j1 = int(np.clip(j0 + 1, 0, core.GRID_CFG.nx - 1))
                    
                    # Interpolation bilinéaire
                    sy = i_float - i0
                    sx = j_float - j0
                    
                    w00 = (1 - sx) * (1 - sy)
                    w10 = sx * (1 - sy)
                    w01 = (1 - sx) * sy
                    w11 = sx * sy
                    
                    # Interpoler la température à la position exacte de la station GP2
                    temp_at_station = None
                    if forecast_field.temp is not None:
                        temp_at_station = (
                            forecast_field.temp[i0, j0] * w00 +
                            forecast_field.temp[i0, j1] * w10 +
                            forecast_field.temp[i1, j0] * w01 +
                            forecast_field.temp[i1, j1] * w11
                        )
                        temp_at_station = float(temp_at_station) if not np.isnan(temp_at_station) else None
                    
                    # Interpoler l'humidité relative à la position exacte de la station GP2
                    rh_at_station = None
                    if forecast_field.rh is not None:
                        rh_at_station = (
                            forecast_field.rh[i0, j0] * w00 +
                            forecast_field.rh[i0, j1] * w10 +
                            forecast_field.rh[i1, j0] * w01 +
                            forecast_field.rh[i1, j1] * w11
                        )
                        rh_at_station = float(rh_at_station) if not np.isnan(rh_at_station) else None
                    
                    forecast_temps.append({
                        "hour": h,
                        "temp_min": temp_min,
                        "temp_max": temp_max,
                        "temp_mean": temp_mean,
                        "temp_at_station": temp_at_station,
                        "rh_min": rh_min,
                        "rh_max": rh_max,
                        "rh_mean": rh_mean,
                        "rh_at_station": rh_at_station
                    })
                    
                    if temp_at_station is not None:
                        forecast_temps_at_station.append(temp_at_station)
                        
                except Exception as e:
                    logger.warning(f"Erreur récupération prévision heure {h}: {e}")
                    continue
            
            if forecast_temps:
                # Calculer les statistiques globales pour la température
                all_temps = [t["temp_at_station"] for t in forecast_temps if t["temp_at_station"] is not None]
                all_temps_grid = [t["temp_mean"] for t in forecast_temps if t["temp_mean"] is not None]
                
                # Calculer les statistiques globales pour l'humidité relative
                all_rh = [t["rh_at_station"] for t in forecast_temps if t["rh_at_station"] is not None]
                all_rh_grid = [t["rh_mean"] for t in forecast_temps if t["rh_mean"] is not None]
                
                forecast_data = {
                    "available": True,
                    "hour": hour,
                    "model": model,
                    "grid": {
                        "ny": core.GRID_CFG.ny,
                        "nx": core.GRID_CFG.nx,
                        "lat_min": float(core.GRID_CFG.lat_min),
                        "lat_max": float(core.GRID_CFG.lat_max),
                        "lon_min": float(core.GRID_CFG.lon_min),
                        "lon_max": float(core.GRID_CFG.lon_max),
                    },
                    "forecast_timeseries": forecast_temps,
                    "station_position": {
                        "lat": float(station_lat),
                        "lon": float(station_lon)
                    }
                }
                
                if all_temps:
                    forecast_data["temp_stats_at_station"] = {
                        "min": float(min(all_temps)),
                        "max": float(max(all_temps)),
                        "mean": float(np.mean(all_temps)),
                        "count": len(all_temps)
                    }
                
                if all_temps_grid:
                    forecast_data["temp_stats_grid"] = {
                        "min": float(min(all_temps_grid)),
                        "max": float(max(all_temps_grid)),
                        "mean": float(np.mean(all_temps_grid))
                    }
                
                if all_rh:
                    forecast_data["rh_stats_at_station"] = {
                        "min": float(min(all_rh)),
                        "max": float(max(all_rh)),
                        "mean": float(np.mean(all_rh)),
                        "count": len(all_rh)
                    }
                
                if all_rh_grid:
                    forecast_data["rh_stats_grid"] = {
                        "min": float(min(all_rh_grid)),
                        "max": float(max(all_rh_grid)),
                        "mean": float(np.mean(all_rh_grid))
                    }
        except Exception as e:
            logger.warning(f"Impossible de récupérer les données de prévision: {e}")
            forecast_data = {"available": False}
        
        # Ajouter la question de l'utilisateur à la conversation
        chatbot.add_message("user", question)
        
        # Générer la réponse avec gestion d'erreur robuste
        try:
            response = chatbot.generate_response(question, station_data, forecast_data)
        except Exception as e:
            logger.error(f"Erreur lors de la génération de la réponse: {e}", exc_info=True)
            # En cas d'erreur, utiliser le mode dégradé
            try:
                response = chatbot._fallback_response(question, station_data, forecast_data)
                if not response or len(response.strip()) == 0:
                    response = "Désolé, une erreur s'est produite lors du traitement de votre question."
            except Exception as e2:
                logger.error(f"Erreur même en mode dégradé: {e2}")
                response = "Désolé, une erreur technique s'est produite. Veuillez réessayer plus tard."
                if not chatbot_available:
                    response += "\n\nNote: Le chatbot fonctionne en mode dégradé car la clé API Cerebras n'est pas configurée."
        
        # Ajouter la réponse à la conversation
        chatbot.add_message("assistant", response)
        
        # Sauvegarder automatiquement la conversation
        try:
            conv_id = chatbot.save_conversation()
        except Exception as e:
            logger.warning(f"Erreur lors de la sauvegarde de la conversation: {e}")
            conv_id = None
        
        # Récupérer les statistiques d'utilisation
        try:
            usage_summary = chatbot.get_usage_summary()
        except Exception as e:
            logger.warning(f"Erreur lors de la récupération des statistiques: {e}")
            usage_summary = {}
        
        return jsonify({
            "response": response,
            "status": "ok",
            "timestamp": datetime.now().isoformat(),
            "conversation_id": conv_id,
            "usage": usage_summary,
            "messages": chatbot.get_messages(),
            "chatbot_mode": "degraded" if not chatbot_available else "full"
        })
        
    except Exception as e:
        logger.error(f"Erreur dans api_chat: {e}", exc_info=True)
        return jsonify({
            "error": "Erreur lors du traitement de la question",
            "message": str(e),
            "status": "error"
        }), 500


@app.route("/api/chat/conversations", methods=["GET"])
def api_list_conversations():
    """Liste toutes les conversations sauvegardées"""
    try:
        conversations = chatbot_windy.load_conversations()
        # Formater les conversations pour l'API
        formatted_convs = []
        for conv in conversations:
            formatted_convs.append({
                "id": conv.get("id"),
                "title": conv.get("title", "Sans titre"),
                "timestamp": conv.get("timestamp"),
                "message_count": conv.get("message_count", 0),
                "mode": conv.get("mode", "weather_chat")
            })
        return jsonify({
            "conversations": formatted_convs,
            "status": "ok"
        })
    except Exception as e:
        logger.error(f"Erreur liste conversations: {e}")
        return jsonify({
            "error": "Erreur lors de la récupération des conversations",
            "status": "error"
        }), 500


@app.route("/api/chat/conversations/<conversation_id>", methods=["GET"])
def api_get_conversation(conversation_id):
    """Récupère une conversation spécifique"""
    try:
        conv = chatbot_windy.load_conversation(conversation_id)
        if conv:
            return jsonify({
                "conversation": conv,
                "status": "ok"
            })
        else:
            return jsonify({
                "error": "Conversation non trouvée",
                "status": "error"
            }), 404
    except Exception as e:
        logger.error(f"Erreur récupération conversation: {e}")
        return jsonify({
            "error": "Erreur lors de la récupération de la conversation",
            "status": "error"
        }), 500


@app.route("/api/chat/conversations/<conversation_id>", methods=["DELETE"])
def api_delete_conversation(conversation_id):
    """Supprime une conversation"""
    try:
        if chatbot_windy.delete_conversation(conversation_id):
            return jsonify({
                "status": "ok",
                "message": "Conversation supprimée"
            })
        else:
            return jsonify({
                "error": "Erreur lors de la suppression",
                "status": "error"
            }), 500
    except Exception as e:
        logger.error(f"Erreur suppression conversation: {e}")
        return jsonify({
            "error": "Erreur lors de la suppression de la conversation",
            "status": "error"
        }), 500


@app.route("/api/chat/usage", methods=["GET"])
def api_get_usage():
    """Récupère les statistiques d'utilisation Cerebras"""
    try:
        if not chatbot_windy.CEREBRAS_AVAILABLE:
            return jsonify({
                "usage": {
                    "available": False,
                    "message": "Chatbot non disponible - Clé API manquante"
                },
                "status": "ok"
            })
        
        chatbot = chatbot_windy.get_chatbot()
        usage = chatbot.get_usage_summary()
        return jsonify({
            "usage": usage,
            "status": "ok"
        })
    except Exception as e:
        logger.error(f"Erreur récupération usage: {e}")
        return jsonify({
            "error": "Erreur lors de la récupération des statistiques",
            "status": "error"
        }), 500


# Routes pour servir les fichiers JavaScript depuis templates/
# Ces routes sont spécifiques aux fichiers .js et .glsl pour ne pas intercepter les routes API
@app.route("/<filename>.js")
def serve_js(filename):
    """Sert les fichiers JS depuis templates/"""
    templates_dir = os.path.join(app.root_path, 'templates')
    file_path = os.path.join(templates_dir, f"{filename}.js")
    if os.path.isfile(file_path):
        return send_from_directory(templates_dir, f"{filename}.js")
    return "", 404


# ===== ENDPOINTS POUR LA GÉNÉRATION DE RAPPORTS (22.py) =====

def find_latest_data_file(data_dir_param: str = None):
    """
    Trouve le fichier le plus récent dans le dossier data.
    
    Args:
        data_dir_param: (optionnel) Chemin du dossier de données personnalisé.
                       Si None ou "data", utilise le dossier par défaut.
    """
    # Utiliser le dossier personnalisé si fourni, sinon le dossier par défaut
    if data_dir_param:
        # Convertir en Path (essayer d'abord comme chemin absolu, puis relatif)
        custom_path = Path(data_dir_param)
        
        # Si le chemin n'est pas absolu et n'existe pas, essayer depuis le répertoire parent
        if not custom_path.is_absolute() and not custom_path.exists():
            server_dir = Path(__file__).parent
            custom_path = server_dir / data_dir_param
        
        # Vérifier que le dossier existe
        if not custom_path.exists() or not custom_path.is_dir():
            logger.error(f"Dossier personnalisé non trouvé: {custom_path}")
            logger.error(f"Chemin absolu: {custom_path.resolve()}")
            # Vérifier si le dossier par défaut existe
            if core.STATION_CFG.data_dir.exists():
                logger.warning("Utilisation du dossier par défaut à la place")
                data_dir = core.STATION_CFG.data_dir
            else:
                logger.error(f"Le dossier par défaut n'existe pas non plus: {core.STATION_CFG.data_dir}")
                return None
        else:
            # Résoudre le chemin pour comparer avec le dossier par défaut
            resolved_custom = custom_path.resolve()
            
            # Vérifier si le dossier par défaut existe avant de comparer
            if core.STATION_CFG.data_dir.exists():
                default_resolved = core.STATION_CFG.data_dir.resolve()
                # Si le chemin résolu correspond exactement au dossier par défaut, utiliser le défaut
                if resolved_custom == default_resolved:
                    data_dir = core.STATION_CFG.data_dir
                    logger.info(f"Chemin résolu correspond au dossier par défaut, utilisation du défaut: {data_dir}")
                else:
                    data_dir = custom_path
                    logger.info(f"Utilisation du dossier personnalisé: {data_dir}")
            else:
                # Le dossier par défaut n'existe pas, utiliser le dossier personnalisé
                data_dir = custom_path
                logger.info(f"Utilisation du dossier personnalisé (dossier par défaut inexistant): {data_dir}")
    else:
        # Utiliser le dossier par défaut depuis STATION_CFG
        try:
            data_dir = core.STATION_CFG.data_dir
            logger.info(f"Utilisation du dossier par défaut depuis STATION_CFG: {data_dir}")
            if not data_dir.exists():
                # Essayer de créer le dossier s'il n'existe pas
                try:
                    data_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(f"Dossier data par défaut créé: {data_dir}")
                except Exception as e:
                    logger.error(f"Impossible de créer le dossier data par défaut: {e}")
                    return None
        except Exception as e:
            # Fallback si STATION_CFG n'est pas disponible
            logger.warning(f"Erreur lors de l'accès à STATION_CFG: {e}")
            data_dir = Path(__file__).parent / "data"
            logger.info(f"Utilisation du dossier par défaut (fallback): {data_dir}")
            if not data_dir.exists():
                # Essayer de créer le dossier fallback
                try:
                    data_dir.mkdir(parents=True, exist_ok=True)
                    logger.info(f"Dossier data fallback créé: {data_dir}")
                except Exception as e2:
                    logger.error(f"Le dossier fallback n'existe pas et n'a pas pu être créé: {e2}")
                    return None
    
    logger.info(f"Recherche du dossier data: {data_dir}")
    logger.info(f"Chemin absolu: {data_dir.resolve()}")
    logger.info(f"Dossier existe: {data_dir.exists()}")
    
    if not data_dir.exists():
        logger.error(f"Dossier data non trouvé: {data_dir}")
        logger.error(f"Chemin absolu: {data_dir.resolve()}")
        if not data_dir_param:
            logger.error(f"Répertoire parent: {Path(__file__).parent}")
            logger.error(f"Fichiers dans le répertoire parent: {list(Path(__file__).parent.iterdir())}")
        else:
            logger.error(f"Dossier personnalisé demandé: {data_dir_param}")
        return None
    
    # Vérifier qu'il y a des fichiers dans le dossier
    all_files_in_dir = [f for f in data_dir.iterdir() if f.is_file()]
    logger.info(f"Fichiers dans le dossier data: {len(all_files_in_dir)}")
    if all_files_in_dir:
        logger.info(f"Exemples de fichiers: {[f.name for f in all_files_in_dir[:10]]}")
    
    # Chercher tous les fichiers GP2_*.txt
    data_files = list(data_dir.glob("GP2_*.txt"))
    logger.info(f"Fichiers GP2_*.txt trouvés: {len(data_files)}")
    
    # Si aucun fichier GP2_*.txt, essayer avec le nom de la station
    if not data_files:
        station_name = core.STATION_CFG.name
        logger.info(f"Aucun fichier GP2_*.txt trouvé, recherche avec pattern {station_name}_*.txt")
        data_files = list(data_dir.glob(f"{station_name}_*.txt"))
        logger.info(f"Fichiers {station_name}_*.txt trouvés: {len(data_files)}")
    
    if not data_files:
        logger.warning(f"Aucun fichier GP2_*.txt ou {core.STATION_CFG.name}_*.txt trouvé dans {data_dir}")
        # Lister tous les fichiers pour déboguer
        all_files = [f for f in data_dir.iterdir() if f.is_file()]
        logger.warning(f"Fichiers dans le dossier data: {[f.name for f in all_files]}")
        logger.warning(f"Patterns recherchés: GP2_*.txt, {core.STATION_CFG.name}_*.txt")
        return None
    
    # Afficher les fichiers trouvés
    for f in data_files:
        logger.info(f"  - {f.name} (modifié: {datetime.fromtimestamp(f.stat().st_mtime)})")
    
    # Retourner le fichier le plus récent (par date de modification)
    latest_file = max(data_files, key=lambda f: f.stat().st_mtime)
    logger.info(f"Fichier le plus récent sélectionné: {latest_file.name}")
    return latest_file


def read_data_file(file_path, date_debut, date_fin):
    """Lit un fichier de données et filtre par plage de dates"""
    try:
        logger.info(f"Lecture du fichier: {file_path}")
        logger.info(f"Plage de dates demandée: {date_debut} à {date_fin}")
        
        # Lire le fichier en sautant la première ligne d'en-tête
        # Le fichier utilise des espaces multiples comme séparateur
        # Le fichier a 7 colonnes: Date, Heure, Power, Speed#@1m, Dir, RH, AirTemp
        # On doit combiner Date et Heure en un seul Timestamp
        try:
            # Lire avec 7 colonnes car le fichier a Date et Heure séparées
            column_names_7 = ['Date', 'Heure', 'Power', 'Speed#@1m', 'Dir', 'RH', 'AirTemp']
            df = pd.read_csv(
                file_path, 
                sep=r'\s+', 
                skiprows=1, 
                encoding='utf-8', 
                engine='python',
                names=column_names_7,
                header=None
            )
            
            # Combiner Date et Heure en un seul Timestamp
            df['Timestamp'] = df['Date'].astype(str) + ' ' + df['Heure'].astype(str)
            # Supprimer les colonnes Date et Heure
            df = df.drop(columns=['Date', 'Heure'])
            # Réorganiser les colonnes: Timestamp en premier
            df = df[['Timestamp', 'Power', 'Speed#@1m', 'Dir', 'RH', 'AirTemp']]
            
        except Exception as e:
            logger.error(f"Erreur lors de la lecture avec sep=r'\\s+': {e}")
            # Essayer avec un séparateur d'espace simple
            try:
                column_names_7 = ['Date', 'Heure', 'Power', 'Speed#@1m', 'Dir', 'RH', 'AirTemp']
                df = pd.read_csv(
                    file_path, 
                    delimiter=' ', 
                    skiprows=1, 
                    encoding='utf-8',
                    names=column_names_7,
                    header=None
                )
                # Combiner Date et Heure en un seul Timestamp
                df['Timestamp'] = df['Date'].astype(str) + ' ' + df['Heure'].astype(str)
                df = df.drop(columns=['Date', 'Heure'])
                df = df[['Timestamp', 'Power', 'Speed#@1m', 'Dir', 'RH', 'AirTemp']]
            except Exception as e2:
                logger.error(f"Erreur lors de la lecture avec delimiter=' ': {e2}")
                raise
        
        logger.info(f"Fichier lu: {len(df)} lignes, {len(df.columns)} colonnes")
        logger.info(f"Colonnes détectées: {list(df.columns)}")
        if len(df) > 0:
            logger.info(f"Première ligne de données: {df.iloc[0].to_dict()}")
        
        # Vérifier que nous avons exactement 6 colonnes
        if len(df.columns) != 6:
            logger.error(f"Nombre de colonnes incorrect: {len(df.columns)} au lieu de 6")
            logger.error(f"Colonnes détectées: {list(df.columns)}")
            if len(df.columns) > 6:
                logger.warning(f"On garde les 6 premières colonnes")
                df = df.iloc[:, :6]
                df.columns = ['Timestamp', 'Power', 'Speed#@1m', 'Dir', 'RH', 'AirTemp']
            else:
                return None, 0, 0
        
        # Les colonnes sont déjà nommées correctement grâce à names=column_names
        logger.info(f"Colonnes finales: {list(df.columns)}")
        
        # Convertir les valeurs numériques (remplacer les virgules par des points)
        numeric_cols = ['Power', 'Speed#@1m', 'Dir', 'RH', 'AirTemp']
        for col in numeric_cols:
            if col in df.columns:
                # Convertir en string, remplacer virgule par point, puis utiliser pd.to_numeric avec errors='coerce'
                df[col] = pd.to_numeric(
                    df[col].astype(str).str.replace(',', '.'), 
                    errors='coerce'
                )
            
        # Convertir la colonne Timestamp en datetime
        # Le format dans le fichier est: DD/MM/YYYY HH:MM:SS (ex: 15/11/2024 14:11:00)
        if len(df) > 0:
            first_timestamp = str(df['Timestamp'].iloc[0])
            logger.info(f"Premier timestamp brut: '{first_timestamp}'")
            
            # Parser le timestamp combiné
            df['Timestamp'] = pd.to_datetime(df['Timestamp'], format='%d/%m/%Y %H:%M:%S', errors='coerce', dayfirst=True)
            
            # Si ça n'a pas marché, essayer d'autres formats
            if df['Timestamp'].isna().sum() > len(df) * 0.5:  # Si plus de 50% sont invalides
                logger.warning("Format de date principal échoué, essai avec format alternatif")
                df['Timestamp'] = pd.to_datetime(df['Timestamp'], errors='coerce', dayfirst=True)
            
        # Supprimer les lignes avec timestamp invalide
        initial_count = len(df)
        df = df.dropna(subset=['Timestamp'])
        logger.info(f"Après nettoyage des timestamps: {len(df)} lignes valides (sur {initial_count})")
        
        if len(df) == 0:
            logger.error("Aucune ligne avec timestamp valide")
            return None, initial_count, 0
        
        # Afficher la plage de dates disponible dans le fichier
        min_date = df['Timestamp'].min()
        max_date = df['Timestamp'].max()
        logger.info(f"Plage de dates disponible dans le fichier: {min_date} à {max_date}")
        
        # Convertir les dates de début et fin (format YYYY-MM-DD depuis le frontend)
        try:
            date_debut_dt = pd.to_datetime(date_debut)
            date_fin_dt = pd.to_datetime(date_fin)
            # Ajouter la fin de journée pour inclure toute la journée de fin
            date_fin_dt = date_fin_dt.replace(hour=23, minute=59, second=59)
        except Exception as e:
            logger.error(f"Erreur conversion dates: {e}")
            return None, len(df), 0
        
        logger.info(f"Dates converties - Début: {date_debut_dt}, Fin: {date_fin_dt}")
        
        # Filtrer par plage de dates
        df_filtered = df[(df['Timestamp'] >= date_debut_dt) & (df['Timestamp'] <= date_fin_dt)]
        logger.info(f"Après filtrage par dates: {len(df_filtered)} lignes (sur {len(df)})")
        
        if len(df_filtered) == 0:
            logger.warning(f"Aucune donnée dans la plage {date_debut_dt} à {date_fin_dt}")
            logger.warning(f"Plage disponible: {min_date} à {max_date}")
            return None, len(df), 0
        
        # Définir Timestamp comme index
        df_filtered = df_filtered.set_index('Timestamp')
        
        return df_filtered, len(df), len(df_filtered)
    except FileNotFoundError as e:
        logger.error(f"Fichier non trouvé: {e}")
        return None, 0, 0
    except pd.errors.EmptyDataError as e:
        logger.error(f"Fichier vide: {e}")
        return None, 0, 0
    except Exception as e:
        logger.error(f"Erreur lecture fichier: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None, 0, 0


@app.route("/api/reports/generate", methods=["POST"])
def api_generate_report():
    """
    Génère un rapport météorologique complet en utilisant 22.py
    
    Paramètres (dans le body JSON):
        date_debut: Date de début (requis)
        date_fin: Date de fin (requis)
        periode_type: Type de période (défaut: 'Journalier')
        audience: Audience cible (défaut: 'Opérateurs Terrain')
        data_dir: (optionnel) Chemin du dossier de données personnalisé
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Aucune donnée fournie", "status": "error"}), 400
        
        date_debut = data.get('date_debut')
        date_fin = data.get('date_fin')
        periode_type = data.get('periode_type', 'Journalier')
        audience = data.get('audience', 'Opérateurs Terrain')
        custom_data_dir = data.get('data_dir', None)
        
        if not date_debut or not date_fin:
            return jsonify({"error": "Les dates de début et de fin sont requises", "status": "error"}), 400
        
        # Trouver le fichier le plus récent
        latest_file = find_latest_data_file(data_dir_param=custom_data_dir)
        if not latest_file:
            return jsonify({
                "error": "Aucun fichier de données trouvé dans le dossier data",
                "status": "error"
            }), 404
        
        # Lire et filtrer les données
        df_filtered, total_rows, filtered_rows = read_data_file(latest_file, date_debut, date_fin)
        
        if df_filtered is None:
            # Essayer de lire le fichier pour obtenir la plage de dates disponible
            try:
                # Le fichier a 7 colonnes: Date, Heure, puis les 5 valeurs
                column_names_7 = ['Date', 'Heure', 'Power', 'Speed#@1m', 'Dir', 'RH', 'AirTemp']
                df_temp = pd.read_csv(
                    latest_file, 
                    sep=r'\s+', 
                    skiprows=1, 
                    encoding='utf-8', 
                    engine='python',
                    names=column_names_7,
                    header=None
                )
                
                # Combiner Date et Heure en Timestamp
                df_temp['Timestamp'] = df_temp['Date'].astype(str) + ' ' + df_temp['Heure'].astype(str)
                df_temp = df_temp.drop(columns=['Date', 'Heure'])
                
                # Convertir les valeurs numériques
                numeric_cols = ['Power', 'Speed#@1m', 'Dir', 'RH', 'AirTemp']
                for col in numeric_cols:
                    df_temp[col] = pd.to_numeric(
                        df_temp[col].astype(str).str.replace(',', '.'), 
                        errors='coerce'
                    )
                
                df_temp['Timestamp'] = pd.to_datetime(df_temp['Timestamp'], format='%d/%m/%Y %H:%M:%S', errors='coerce', dayfirst=True)
                df_temp = df_temp.dropna(subset=['Timestamp'])
                if len(df_temp) > 0:
                    min_date = df_temp['Timestamp'].min().strftime('%d/%m/%Y %H:%M:%S')
                    max_date = df_temp['Timestamp'].max().strftime('%d/%m/%Y %H:%M:%S')
                    date_range_info = f"Plage disponible dans le fichier: {min_date} à {max_date}"
                else:
                    date_range_info = "Aucune date valide trouvée dans le fichier"
            except Exception as e:
                logger.error(f"Erreur lors de la lecture pour obtenir la plage: {e}")
                import traceback
                logger.error(traceback.format_exc())
                date_range_info = f"Impossible de déterminer la plage de dates: {str(e)}"
            
            return jsonify({
                "error": f"Aucune donnée trouvée dans la plage de dates demandée ({date_debut} à {date_fin}). {date_range_info}. Le fichier contient {total_rows} lignes au total.",
                "status": "error",
                "file_name": latest_file.name,
                "total_rows": total_rows,
                "filtered_rows": 0,
                "date_range_info": date_range_info
            }), 400
        
        if len(df_filtered) == 0:
            return jsonify({
                "error": f"Aucune donnée ne correspond à la plage de dates demandée ({date_debut} à {date_fin})",
                "status": "error",
                "file_name": latest_file.name,
                "total_rows": total_rows,
                "filtered_rows": 0
            }), 400
        
        # Importer et utiliser les classes de 22.py
        try:
            import sys
            import importlib.util
            from pathlib import Path as PathLib
            
            # Mock Streamlit pour permettre l'import de 22.py
            class MockStreamlit:
                def __init__(self):
                    self.session_state = {}
                def warning(self, msg): logger.warning(str(msg))
                def error(self, msg): logger.error(str(msg))
                def info(self, msg): logger.info(str(msg))
                def success(self, msg): logger.info(f"SUCCESS: {str(msg)}")
                def spinner(self, msg): return self
                def __enter__(self): return self
                def __exit__(self, *args): pass
            
            sys.modules['streamlit'] = MockStreamlit()
            
            # Importer 22.py
            report_22_path = PathLib(__file__).parent.parent / "22.py"
            if not report_22_path.exists():
                return jsonify({
                    "error": "Fichier 22.py non trouvé",
                    "status": "error"
                }), 500
            
            spec = importlib.util.spec_from_file_location("report_22", report_22_path)
            report_22 = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(report_22)
            
            # Extraire les classes nécessaires
            DataAnalyzer = report_22.DataAnalyzer
            ReportGenerator = report_22.ReportGenerator
            WindRoseGenerator = report_22.WindRoseGenerator
            GraphGenerator = report_22.GraphGenerator
            PDFGenerator = report_22.PDFGenerator
            
            # Créer les instances
            data_analyzer = DataAnalyzer()
            report_generator = ReportGenerator()
            wind_rose_generator = WindRoseGenerator()
            graph_generator = GraphGenerator()
            pdf_generator = PDFGenerator()
            
            # Préparation des données nettoyées
            logger.info(f"Avant nettoyage: {len(df_filtered)} lignes, colonnes: {list(df_filtered.columns)}")
            logger.info(f"Type d'index avant parse_timestamp_column: {type(df_filtered.index)}")
            
            df_clean = data_analyzer.clean_numeric_data(df_filtered.copy())
            df_clean = data_analyzer.parse_timestamp_column(df_clean)
            
            logger.info(f"Après nettoyage: {len(df_clean)} lignes, colonnes: {list(df_clean.columns)}")
            logger.info(f"Type d'index après parse_timestamp_column: {type(df_clean.index)}")
            if len(df_clean) > 0:
                logger.info(f"Plage de dates dans df_clean: {df_clean.index.min()} à {df_clean.index.max()}")
                logger.info(f"Colonnes numériques disponibles: {[col for col in ['AirTemp', 'Speed#@1m', 'RH', 'Power'] if col in df_clean.columns]}")
            
            if len(df_clean) == 0:
                return jsonify({
                    "error": "Aucune donnée valide après nettoyage",
                    "status": "error"
                }), 400
            
            # Étape 1: Analyse des données
            analysis_json = data_analyzer.analyze_data(
                df_clean, periode_type, date_debut, date_fin
            )
            
            # Étape 2: Génération de la Wind Rose
            wind_rose_fig = wind_rose_generator.generate_wind_rose_plotly(
                analysis_json['wind_rose_data']
            )
            
            # Convertir la figure Plotly en JSON
            wind_rose_json = None
            if wind_rose_fig:
                import plotly.io as pio
                wind_rose_json = json.loads(pio.to_json(wind_rose_fig))
            
            # Étape 3: Génération du rapport COMPLET par LLM
            report_markdown = report_generator.generate_report(
                analysis_json, periode_type, audience, df=df_clean
            )
            
            # Étape 4: Génération des graphiques supplémentaires (avec dates pour limiter les séries temporelles)
            logger.info(f"Génération des graphiques avec dates: {date_debut} à {date_fin}")
            logger.info(f"DataFrame passé à generate_all_graphs: {len(df_clean)} lignes, index type: {type(df_clean.index)}")
            additional_graphs = graph_generator.generate_all_graphs(
                df_clean, periode_type, analysis_json=analysis_json, date_debut=date_debut, date_fin=date_fin
            )
            logger.info(f"Graphiques générés: {list(additional_graphs.keys()) if additional_graphs else 'Aucun'}")
            
            # Convertir les graphiques Plotly en JSON
            additional_graphs_json = {}
            if additional_graphs:
                import plotly.io as pio
                for key, fig in additional_graphs.items():
                    if fig:
                        additional_graphs_json[key] = json.loads(pio.to_json(fig))
            
            return jsonify({
                "analysis_json": analysis_json,
                "wind_rose_fig": wind_rose_json,
                "report_markdown": report_markdown,
                "additional_graphs": additional_graphs_json,
                "file_name": latest_file.name,
                "total_rows": total_rows,
                "filtered_rows": len(df_clean),
                "status": "ok"
            })
            
        except Exception as e:
            logger.error(f"Erreur lors de l'utilisation de 22.py: {e}")
            import traceback
            return jsonify({
                "error": f"Erreur lors de la génération du rapport: {str(e)}",
                "status": "error",
                "traceback": traceback.format_exc()
            }), 500
            
    except Exception as e:
        logger.error(f"Erreur génération rapport: {e}")
        import traceback
        return jsonify({
            "error": f"Erreur lors de la génération du rapport: {str(e)}",
            "status": "error",
            "traceback": traceback.format_exc()
        }), 500


@app.route("/api/reports/generate-pdf", methods=["POST"])
def api_generate_pdf():
    """Génère un PDF à partir d'un rapport Markdown"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({"error": "Aucune donnée fournie", "status": "error"}), 400
        
        report_markdown = data.get('report_markdown', '')
        wind_rose_fig_json = data.get('wind_rose_fig')
        additional_graphs_json = data.get('additional_graphs', {})
        
        if not report_markdown:
            return jsonify({"error": "Rapport Markdown manquant", "status": "error"}), 400
        
        # Importer PDFGenerator de 22.py
        try:
            import sys
            import importlib.util
            from pathlib import Path as PathLib
            
            # Mock Streamlit
            class MockStreamlit:
                def __init__(self):
                    self.session_state = {}
                def warning(self, msg): logger.warning(str(msg))
                def error(self, msg): logger.error(str(msg))
            
            sys.modules['streamlit'] = MockStreamlit()
            
            report_22_path = PathLib(__file__).parent.parent / "22.py"
            spec = importlib.util.spec_from_file_location("report_22", report_22_path)
            report_22 = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(report_22)
            
            PDFGenerator = report_22.PDFGenerator
            pdf_generator = PDFGenerator()
            
            # Convertir les graphiques JSON en figures Plotly
            figs = []
            if wind_rose_fig_json:
                import plotly.io as pio
                fig = pio.from_json(json.dumps(wind_rose_fig_json))
                figs.append(fig)
                logger.info("Wind rose figure convertie et ajoutée")
            else:
                logger.warning("Wind rose figure JSON manquante")
            
            additional_graphs = {}
            if additional_graphs_json:
                import plotly.io as pio
                for key, fig_json in additional_graphs_json.items():
                    if fig_json:
                        try:
                            additional_graphs[key] = pio.from_json(json.dumps(fig_json))
                            logger.info(f"Graphique {key} converti et ajouté")
                        except Exception as e:
                            logger.error(f"Erreur lors de la conversion du graphique {key}: {e}")
                    else:
                        logger.warning(f"Graphique {key} JSON vide")
                logger.info(f"Total graphiques supplémentaires: {len(additional_graphs)} - Clés: {list(additional_graphs.keys())}")
            else:
                logger.warning("Aucun graphique supplémentaire fourni")
            
            # Générer le PDF
            output_path = tempfile.mktemp(suffix=".pdf")
            logger.info(f"Génération du PDF dans: {output_path}")
            pdf_path = pdf_generator.create_pdf(
                report_markdown,
                figs=figs if figs else None,
                additional_graphs=additional_graphs if additional_graphs else None,
                output_path=output_path
            )
            
            logger.info(f"PDF généré à: {pdf_path}")
            
            if pdf_path and os.path.exists(pdf_path):
                file_size = os.path.getsize(pdf_path)
                logger.info(f"Taille du fichier PDF: {file_size} bytes")
                
                with open(pdf_path, "rb") as f:
                    pdf_bytes = f.read()
                
                logger.info(f"PDF lu: {len(pdf_bytes)} bytes")
                
                # Nettoyer le fichier temporaire
                try:
                    os.remove(pdf_path)
                    logger.info("Fichier temporaire supprimé")
                except Exception as e:
                    logger.warning(f"Impossible de supprimer le fichier temporaire: {e}")
                
                from flask import Response
                filename = f"rapport_meteo_ocp_{datetime.now().strftime('%Y%m%d_%H%M')}.pdf"
                logger.info(f"Envoi du PDF avec le nom: {filename}")
                
                response = Response(
                    pdf_bytes,
                    mimetype='application/pdf',
                    headers={
                        'Content-Disposition': f'attachment; filename="{filename}"',
                        'Content-Length': str(len(pdf_bytes))
                    }
                )
                logger.info("Réponse PDF créée, envoi au client")
                return response
            else:
                logger.error(f"Le fichier PDF n'existe pas: {pdf_path}")
                return jsonify({"error": "Échec de la génération du PDF", "status": "error"}), 500
                
        except Exception as e:
            logger.error(f"Erreur génération PDF: {e}")
            import traceback
            return jsonify({
                "error": f"Erreur lors de la génération du PDF: {str(e)}",
                "status": "error",
                "traceback": traceback.format_exc()
            }), 500
            
    except Exception as e:
        logger.error(f"Erreur génération PDF: {e}")
        import traceback
        return jsonify({
            "error": f"Erreur lors de la génération du PDF: {str(e)}",
            "status": "error",
            "traceback": traceback.format_exc()
        }), 500




def ensure_default_data_dir():
    """Crée le dossier data par défaut s'il n'existe pas"""
    default_data_dir = core.STATION_CFG.data_dir
    
    if not default_data_dir.exists():
        try:
            default_data_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"✅ Dossier data par défaut créé: {default_data_dir}")
            logger.info(f"   Chemin absolu: {default_data_dir.resolve()}")
            # Créer un fichier .gitkeep pour que le dossier soit versionné (si Git est utilisé)
            gitkeep_file = default_data_dir / ".gitkeep"
            if not gitkeep_file.exists():
                gitkeep_file.write_text("# Dossier data - Les fichiers GP2_*.txt seront placés ici\n")
        except Exception as e:
            logger.error(f"❌ Impossible de créer le dossier data par défaut: {e}")
            logger.error(f"   Chemin tenté: {default_data_dir}")
    else:
        logger.info(f"✅ Dossier data par défaut existe: {default_data_dir}")
        # Vérifier qu'il y a des fichiers
        txt_files = list(default_data_dir.glob("*.txt"))
        if txt_files:
            logger.info(f"   {len(txt_files)} fichier(s) .txt trouvé(s)")
        else:
            logger.info(f"   Dossier vide (aucun fichier .txt) - Prêt à recevoir des données")


if __name__ == "__main__":
    logger.info("=" * 60)
    logger.info("Démarrage du serveur Windy Safi")
    logger.info("=" * 60)
    
    # Créer le dossier data par défaut s'il n'existe pas
    ensure_default_data_dir()
    
    # Afficher le statut des clés API
    if chatbot_windy.CEREBRAS_AVAILABLE:
        logger.info("✅ Chatbot disponible (Clé API Cerebras configurée)")
    else:
        logger.warning("⚠️  Chatbot désactivé (Clé API Cerebras manquante - Mode debug)")
        logger.info("   Le serveur peut fonctionner, mais les fonctionnalités chatbot seront indisponibles")
    
    logger.info("Endpoints disponibles:")
    logger.info("  - http://127.0.0.1:5000/ (Interface principale)")
    logger.info("  - http://127.0.0.1:5000/api/health (Santé du serveur)")
    logger.info("  - http://127.0.0.1:5000/api/test/openmeteo (Test API Open-Meteo)")
    logger.info("  - http://127.0.0.1:5000/api/test/forecast (Test prévisions)")
    logger.info("  - http://127.0.0.1:5000/api/diagnostics (Diagnostics complets)")
    if chatbot_windy.CEREBRAS_AVAILABLE:
        logger.info("  - http://127.0.0.1:5000/api/chat (Chatbot météo)")
    else:
        logger.info("  - http://127.0.0.1:5000/api/chat (Chatbot - DÉSACTIVÉ)")
    logger.info("=" * 60)
    
    # Configuration pour le déploiement (utilise les variables d'environnement)
    # En production, les plateformes cloud définissent PORT automatiquement
    host = os.environ.get("HOST", "127.0.0.1")  # Par défaut localhost pour dev local
    port = int(os.environ.get("PORT", 5000))  # Par défaut 5000, mais Railway/Render utilisent leur propre PORT
    
    # Mode debug uniquement en développement local
    debug_mode = os.environ.get("FLASK_DEBUG", "False").lower() == "true"
    
    # Désactiver use_reloader pour éviter les redémarrages constants dus aux changements TensorFlow
    # debug=True reste actif pour les erreurs détaillées, mais sans auto-reload
    logger.info(f"Démarrage sur {host}:{port} (debug={debug_mode})")
    app.run(host=host, port=port, debug=debug_mode, use_reloader=False)
