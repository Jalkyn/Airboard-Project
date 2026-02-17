import React, { useEffect, useRef, useState, memo, useCallback } from 'react';
import TopBar from '../TopBar';
import './WindyMapPage.css';
import { getApiUrl, getWindyIframeSrc, API_ENDPOINTS, API_BASE_URL } from '../../lib/api-config';

type Page = 'home' | 'dashboard' | 'map' | 'rapports' | 'about-us' | 'how-it-works';

interface WindyMapPageProps {
  onNavigate: (page: Page) => void;
}

const WindyMapPage = memo(function WindyMapPage({ onNavigate }: WindyMapPageProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const [isLoaded, setIsLoaded] = useState(false);
  const [hasError, setHasError] = useState(false);
  const [isChecking, setIsChecking] = useState(true);
  const iframeCreatedRef = useRef(false);
  const loadTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const checkTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const intersectionObserverRef = useRef<IntersectionObserver | null>(null);

  // Vérifier si le serveur est accessible
  const checkServer = useCallback(async () => {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 2000); // Réduit à 2s
      
      const response = await fetch(getApiUrl(API_ENDPOINTS.HEALTH), {
        method: 'GET',
        mode: 'cors',
        cache: 'no-cache',
        signal: controller.signal,
      });
      
      clearTimeout(timeoutId);
      
      if (response.ok) {
        setIsChecking(false);
        setHasError(false);
        return true;
      } else {
        setIsChecking(false);
        setHasError(true);
        return false;
      }
    } catch (error: any) {
      console.log('Erreur vérification serveur:', error);
      setIsChecking(false);
      setHasError(true);
      return false;
    }
  }, []);

  // Créer l'iframe de manière optimisée
  const createIframe = useCallback(() => {
    if (iframeCreatedRef.current || iframeRef.current || !containerRef.current) {
      return;
    }

    iframeCreatedRef.current = true;

    const iframe = document.createElement('iframe');
    iframe.id = 'windy-iframe';
    iframe.src = getWindyIframeSrc();
    
    // Optimisations de performance
    iframe.setAttribute('loading', 'eager'); // Charger immédiatement
    iframe.setAttribute('importance', 'high');
    iframe.setAttribute('fetchpriority', 'high');
    
    // Sandbox minimal pour performance (localhost donc sécurisé)
    // Pas de sandbox = meilleures performances
    
    // Styles optimisés pour performance maximale
    Object.assign(iframe.style, {
      width: '100%',
      height: '100%',
      border: 'none',
      position: 'absolute',
      top: '0',
      left: '0',
      zIndex: '1',
      // Optimisations de rendu
      willChange: 'auto', // Pas de will-change pour éviter la consommation mémoire
      backfaceVisibility: 'hidden',
      WebkitBackfaceVisibility: 'hidden',
      display: 'block',
      isolation: 'isolate',
      transform: 'translateZ(0)', // Force l'accélération matérielle
      pointerEvents: 'auto',
      // Optimisations de composition
      contain: 'layout style paint', // CSS Containment maximal
      contentVisibility: 'auto', // Lazy rendering si hors vue
      // Pas de transitions/animations qui pourraient causer du lag
      transition: 'none',
      animation: 'none',
    });
    
    iframe.allow = 'fullscreen';
    
    // Gestionnaires d'événements optimisés
    const handleLoad = () => {
      if (loadTimeoutRef.current) {
        clearTimeout(loadTimeoutRef.current);
        loadTimeoutRef.current = null;
      }
      // Utiliser requestIdleCallback pour ne pas bloquer le thread principal
      if ('requestIdleCallback' in window) {
        requestIdleCallback(() => {
          requestAnimationFrame(() => {
            setIsLoaded(true);
            setHasError(false);
          });
        });
      } else {
        requestAnimationFrame(() => {
          setIsLoaded(true);
          setHasError(false);
        });
      }
    };
    
    const handleError = () => {
      setHasError(true);
      setIsLoaded(false);
      if (loadTimeoutRef.current) {
        clearTimeout(loadTimeoutRef.current);
        loadTimeoutRef.current = null;
      }
    };
    
    // Utiliser { once: true } pour éviter les fuites mémoire
    iframe.addEventListener('load', handleLoad, { once: true, passive: true });
    iframe.addEventListener('error', handleError, { once: true, passive: true });
    
    // Timeout réduit pour détection rapide des erreurs
    loadTimeoutRef.current = setTimeout(() => {
      if (!isLoaded) {
        console.warn('Iframe timeout - mais peut-être toujours en chargement');
        // Ne pas marquer comme erreur immédiatement, laisser plus de temps
      }
    }, 20000); // 20 secondes
    
    containerRef.current.appendChild(iframe);
    iframeRef.current = iframe;
  }, [isLoaded]);

  // Utiliser IntersectionObserver pour charger l'iframe seulement quand visible
  useEffect(() => {
    if (!containerRef.current || iframeCreatedRef.current) return;

    // Vérifier d'abord le serveur
    checkServer().then((serverOk) => {
      if (!serverOk) return;

      // Si le conteneur est déjà visible, créer l'iframe immédiatement
      if (containerRef.current) {
        const rect = containerRef.current.getBoundingClientRect();
        const isVisible = rect.top < window.innerHeight && rect.bottom > 0;
        
        if (isVisible) {
          // Utiliser requestIdleCallback si disponible
          if ('requestIdleCallback' in window) {
            requestIdleCallback(() => {
              createIframe();
            }, { timeout: 100 });
          } else {
            // Sinon utiliser requestAnimationFrame
            requestAnimationFrame(() => {
              createIframe();
            });
          }
        } else {
          // Observer pour charger quand visible
          intersectionObserverRef.current = new IntersectionObserver(
            (entries) => {
              entries.forEach((entry) => {
                if (entry.isIntersecting && !iframeCreatedRef.current) {
                  createIframe();
                  if (intersectionObserverRef.current) {
                    intersectionObserverRef.current.disconnect();
                    intersectionObserverRef.current = null;
                  }
                }
              });
            },
            {
              rootMargin: '50px', // Commencer à charger 50px avant d'être visible
              threshold: 0.01,
            }
          );
          
          if (containerRef.current) {
            intersectionObserverRef.current.observe(containerRef.current);
          }
        }
      }
    });

    return () => {
      if (intersectionObserverRef.current) {
        intersectionObserverRef.current.disconnect();
        intersectionObserverRef.current = null;
      }
      if (checkTimeoutRef.current) {
        clearTimeout(checkTimeoutRef.current);
      }
      if (loadTimeoutRef.current) {
        clearTimeout(loadTimeoutRef.current);
      }
    };
  }, [checkServer, createIframe]);

  // Styles mémorisés pour éviter les re-renders
  const containerStyle = useRef({
    position: 'fixed' as const,
    top: '4rem',
    left: 0,
    right: 0,
    bottom: 0,
    width: '100%',
    height: 'calc(100vh - 4rem)',
    overflow: 'hidden',
    // Optimisations de performance
    willChange: 'auto',
    contain: 'layout style paint', // CSS Containment maximal
    isolation: 'isolate',
    transform: 'translateZ(0)', // Force l'accélération matérielle
    backfaceVisibility: 'hidden',
    WebkitBackfaceVisibility: 'hidden',
    // Pas de transitions qui pourraient causer du lag
    transition: 'none',
  });

  const innerContainerStyle = useRef({
    width: '100%',
    height: '100%',
    position: 'relative' as const,
    // Optimisations supplémentaires
    contain: 'layout style paint',
    isolation: 'isolate',
    transform: 'translateZ(0)',
  });

  const overlayBgStyle = React.useMemo(() => ({
    background: 'var(--background, #0B0F0C)',
    color: 'var(--foreground, #FFFFFF)',
  }), []);

  const loadingOverlayStyle = React.useMemo(() => ({
    pointerEvents: isLoaded ? 'none' as const : 'auto' as const,
    opacity: isLoaded ? 0 : 1,
    transition: 'opacity 0.3s ease-out', // Transition rapide
    willChange: 'opacity',
  }), [isLoaded]);

  const handleRetry = useCallback(() => {
    setIsChecking(true);
    setHasError(false);
    setIsLoaded(false);
    iframeCreatedRef.current = false;
    if (iframeRef.current && iframeRef.current.parentNode) {
      iframeRef.current.parentNode.removeChild(iframeRef.current);
      iframeRef.current = null;
    }
    checkServer().then((serverOk) => {
      if (serverOk) {
        createIframe();
      }
    });
  }, [checkServer, createIframe]);

  return (
    <>
      <TopBar currentPage="map" onNavigate={onNavigate} />
      <div 
        className="windy-map-page"
        ref={containerRef}
        style={containerStyle.current}
      >
        <div 
          style={innerContainerStyle.current}
          suppressHydrationWarning={true}
        >
          {/* Overlays pour loading/error states */}
          {(!isLoaded || isChecking || hasError) && (
            <div 
              className="absolute inset-0 flex items-center justify-center z-10"
              style={{ ...overlayBgStyle, ...loadingOverlayStyle }}
            >
              {isChecking && (
                <div className="text-center">
                  <div className="text-[var(--foreground)] text-lg mb-4">Vérification du serveur...</div>
                  <div className="text-[var(--muted-foreground)] text-sm">
                    Connexion à {API_BASE_URL}
                  </div>
                </div>
              )}

              {!isLoaded && !hasError && !isChecking && (
                <div className="text-center">
                  <div className="text-[var(--foreground)] text-lg mb-4">Chargement de l'interface Windy...</div>
                  <div className="text-[var(--muted-foreground)] text-sm">
                    Veuillez patienter...
                  </div>
                </div>
              )}
              
              {hasError && !isChecking && (
                <div className="text-center max-w-md px-6">
                  <div className="text-[var(--destructive)] text-lg mb-4">⚠️ Serveur Flask non accessible</div>
                  <div className="text-[var(--muted-foreground)] text-sm mb-4">
                    Impossible de se connecter au serveur Flask sur {API_BASE_URL}
                  </div>
                  <div className="text-[var(--muted-foreground)] text-xs mb-4 space-y-2">
                    <div className="bg-[var(--card)] border border-[var(--border)] px-4 py-3 rounded-lg text-left">
                      <div className="font-semibold mb-2 text-[var(--foreground)]">Pour démarrer le serveur :</div>
                      <ol className="list-decimal list-inside space-y-1 text-[var(--muted-foreground)]">
                        <li>Ouvrez un terminal</li>
                        <li>Naviguez vers le dossier Info Windy :<br />
                          <code className="bg-[var(--input)] text-[var(--accent)] px-2 py-1 rounded mt-1 inline-block font-mono">
                            cd "Info Windy"
                          </code>
                        </li>
                        <li>Activez l'environnement virtuel (si nécessaire) :<br />
                          <code className="bg-[var(--input)] text-[var(--accent)] px-2 py-1 rounded mt-1 inline-block font-mono">
                            venv\Scripts\activate
                          </code>
                        </li>
                        <li>Démarrez le serveur :<br />
                          <code className="bg-[var(--input)] text-[var(--accent)] px-2 py-1 rounded mt-1 inline-block font-mono">
                            python Windy_Server.py
                          </code>
                        </li>
                      </ol>
                    </div>
                  </div>
                  <button
                    onClick={handleRetry}
                    className="mt-4 px-6 py-2 bg-[var(--primary)] text-[var(--primary-foreground)] rounded-lg font-semibold hover:opacity-90 transition-opacity"
                  >
                    Réessayer
                  </button>
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </>
  );
});

export default WindyMapPage;
