import { useState, useEffect, useRef } from 'react';
import { getApiUrl, API_ENDPOINTS } from '../lib/api-config';

// Cache global pour partager les données entre composants
let globalCache: {
  data: any;
  timestamp: number;
  promise: Promise<any> | null;
  cacheKey: string;
} = {
  data: null,
  timestamp: 0,
  promise: null,
  cacheKey: '',
};

const CACHE_TTL = 25000; // 25 secondes (moins que le TTL serveur de 30s)

export function useDashboardData(
  dataDir: string | null, 
  isLive: boolean, 
  selectedDate?: Date, 
  selectedHour?: string
) {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const abortControllerRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const loadData = async () => {
      // Annuler la requête précédente si elle existe
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      
      abortControllerRef.current = new AbortController();
      
      // Construire la clé de cache
      const cacheKey = `${dataDir || 'default'}-${isLive ? 'live' : 'historical'}-${selectedDate?.toISOString() || ''}-${selectedHour || ''}`;
      const now = Date.now();
      
      // Vérifier le cache global
      if (globalCache.data && 
          globalCache.cacheKey === cacheKey &&
          globalCache.timestamp + CACHE_TTL > now &&
          globalCache.promise === null) {
        setData(globalCache.data);
        setLoading(false);
        return;
      }
      
      // Si une requête est déjà en cours pour la même clé, attendre sa fin
      if (globalCache.promise && globalCache.cacheKey === cacheKey) {
        try {
          const result = await globalCache.promise;
          setData(result);
          setLoading(false);
          return;
        } catch (e) {
          // Continuer avec une nouvelle requête si l'ancienne a échoué
        }
      }
      
      // Construire l'URL
      let url = getApiUrl(API_ENDPOINTS.DASHBOARD_DATA);
      const params: string[] = [];
      
      if (dataDir && dataDir.trim() !== '' && dataDir.trim().toLowerCase() !== 'data') {
        params.push(`data_dir=${encodeURIComponent(dataDir)}`);
      }
      
      if (!isLive && selectedDate) {
        const dateStr = selectedDate.toISOString().split('T')[0];
        params.push(`target_date=${dateStr}`);
        if (selectedHour) {
          params.push(`target_hour=${selectedHour}`);
        }
      }
      
      if (params.length > 0) {
        url += `?${params.join('&')}`;
      }
      
      // Créer la promesse partagée
      const fetchPromise = fetch(url, {
        signal: abortControllerRef.current.signal,
        cache: 'default', // Permettre le cache navigateur
      }).then(async (response) => {
        if (!response.ok) {
          throw new Error(`HTTP error! status: ${response.status}`);
        }
        return response.json();
      });
      
      globalCache.promise = fetchPromise;
      globalCache.cacheKey = cacheKey;
      
      try {
        const result = await fetchPromise;
        globalCache.data = result;
        globalCache.timestamp = now;
        globalCache.promise = null;
        setData(result);
        setLoading(false);
      } catch (error: any) {
        if (error.name !== 'AbortError') {
          console.error('Erreur lors du chargement des données:', error);
          setData(null);
          setLoading(false);
        }
        globalCache.promise = null;
      }
    };
    
    loadData();
    
    // Intervalle plus long en mode live (60 secondes au lieu de 30)
    let interval: NodeJS.Timeout | null = null;
    if (isLive) {
      interval = setInterval(loadData, 60000); // 60 secondes
    }
    
    return () => {
      if (interval) clearInterval(interval);
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [dataDir, isLive, selectedDate, selectedHour]);
  
  return { data, loading };
}

