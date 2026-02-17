/**
 * API Configuration
 * 
 * This file centralizes API URL configuration using environment variables.
 * For Vercel deployment, set VITE_API_URL in the Vercel dashboard (e.g. https://your-backend.railway.app).
 * 
 * Default: http://localhost:5000 (for local development)
 */

const rawApiUrl = import.meta.env.VITE_API_URL;
// Never use empty string so iframe never gets a relative URL (which would load the frontend origin, e.g. Vercel)
export const API_BASE_URL =
  typeof rawApiUrl === 'string' && rawApiUrl.trim() !== ''
    ? rawApiUrl.trim().replace(/\/+$/, '')
    : 'http://localhost:5000';

/**
 * Get the full API URL for a given endpoint
 * @param endpoint - API endpoint (e.g., '/api/dashboard/data')
 * @returns Full URL (e.g., 'http://localhost:5000/api/dashboard/data')
 */
export function getApiUrl(endpoint: string): string {
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  return `${API_BASE_URL}${cleanEndpoint}`;
}

/**
 * URL for the Windy interface iframe (Flask serves it at /).
 * Always returns an absolute URL so the iframe never loads the frontend (Vercel) by mistake.
 */
export function getWindyIframeSrc(): string {
  const url = getApiUrl(API_ENDPOINTS.WINDY_APP);
  if (!url.startsWith('http://') && !url.startsWith('https://')) {
    return `${API_BASE_URL}/`;
  }
  return url;
}

/**
 * API endpoints
 */
export const API_ENDPOINTS = {
  DASHBOARD_DATA: '/api/dashboard/data',
  DATA_DIR: '/api/data-dir',
  REPORTS_GENERATE: '/api/reports/generate',
  REPORTS_GENERATE_PDF: '/api/reports/generate-pdf',
  HEALTH: '/api/health',
  WINDY_APP: '/', // Root endpoint for Windy iframe (Flask route "/")
} as const;
