/**
 * API Configuration
 * 
 * This file centralizes API URL configuration using environment variables.
 * For Vercel deployment, set VITE_API_URL in the Vercel dashboard.
 * 
 * Default: http://localhost:5000 (for local development)
 */

export const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:5000';

/**
 * Get the full API URL for a given endpoint
 * @param endpoint - API endpoint (e.g., '/api/dashboard/data')
 * @returns Full URL (e.g., 'http://localhost:5000/api/dashboard/data')
 */
export function getApiUrl(endpoint: string): string {
  // Remove leading slash if present to avoid double slashes
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  // Ensure API_BASE_URL doesn't end with a slash
  const cleanBaseUrl = API_BASE_URL.endsWith('/') ? API_BASE_URL.slice(0, -1) : API_BASE_URL;
  return `${cleanBaseUrl}${cleanEndpoint}`;
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
  WINDY_APP: '/', // Root endpoint for Windy iframe
} as const;
