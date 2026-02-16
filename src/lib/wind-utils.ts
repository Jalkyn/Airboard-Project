// Wind calculation utilities

export function calculateWindSpeed(u: number, v: number): number {
  return Math.sqrt(u * u + v * v);
}

export function calculateWindDirection(u: number, v: number): number {
  // Direction the wind is coming FROM (meteorological convention)
  const dir = (450 - (Math.atan2(v, u) * 180) / Math.PI) % 360;
  return dir;
}

export function interpolateColor(
  value: number,
  min: number,
  max: number
): string {
  // Temperature color palette (5 stops)
  const colors = [
    { stop: 0, color: '#2c7bb6' }, // Cold blue
    { stop: 0.25, color: '#abd9e9' }, // Light blue
    { stop: 0.5, color: '#ffffbf' }, // Yellow
    { stop: 0.75, color: '#fdae61' }, // Orange
    { stop: 1, color: '#d7191c' }, // Hot red
  ];

  // Normalize value to 0-1 range
  const normalized = Math.max(0, Math.min(1, (value - min) / (max - min)));

  // Find the two color stops to interpolate between
  let lowerStop = colors[0];
  let upperStop = colors[colors.length - 1];

  for (let i = 0; i < colors.length - 1; i++) {
    if (normalized >= colors[i].stop && normalized <= colors[i + 1].stop) {
      lowerStop = colors[i];
      upperStop = colors[i + 1];
      break;
    }
  }

  // Interpolate between the two colors
  const localNormalized =
    (normalized - lowerStop.stop) / (upperStop.stop - lowerStop.stop);

  const r1 = parseInt(lowerStop.color.slice(1, 3), 16);
  const g1 = parseInt(lowerStop.color.slice(3, 5), 16);
  const b1 = parseInt(lowerStop.color.slice(5, 7), 16);

  const r2 = parseInt(upperStop.color.slice(1, 3), 16);
  const g2 = parseInt(upperStop.color.slice(3, 5), 16);
  const b2 = parseInt(upperStop.color.slice(5, 7), 16);

  const r = Math.round(r1 + (r2 - r1) * localNormalized);
  const g = Math.round(g1 + (g2 - g1) * localNormalized);
  const b = Math.round(b1 + (b2 - b1) * localNormalized);

  return `rgb(${r}, ${g}, ${b})`;
}

export interface GridPoint {
  lat: number;
  lon: number;
  temp: number;
  u: number;
  v: number;
}

export interface WeatherData {
  timestamp: Date;
  grid: GridPoint[];
  tempMin: number;
  tempMax: number;
}

// Generate mock data for the grid (21x21 points around Safi)
export function generateMockWeatherData(
  timeOffsetMinutes: number = 0
): WeatherData {
  const centerLat = 32.232333;
  const centerLon = -9.251556;
  const gridSize = 21;
  const offset = 0.25;

  const grid: GridPoint[] = [];

  for (let i = 0; i < gridSize; i++) {
    for (let j = 0; j < gridSize; j++) {
      const lat = centerLat - offset + (i / (gridSize - 1)) * offset * 2;
      const lon = centerLon - offset + (j / (gridSize - 1)) * offset * 2;

      // Generate pseudo-realistic wind and temperature data
      const noise = Math.sin(lat * 10 + lon * 10 + timeOffsetMinutes * 0.1);
      const temp = 20 + 8 * noise + Math.random() * 3;
      const u = 2 + 4 * Math.cos(lat * 5 + timeOffsetMinutes * 0.05);
      const v = 1 + 3 * Math.sin(lon * 5 + timeOffsetMinutes * 0.05);

      grid.push({ lat, lon, temp, u, v });
    }
  }

  const temps = grid.map((p) => p.temp);
  const tempMin = Math.min(...temps);
  const tempMax = Math.max(...temps);

  return {
    timestamp: new Date(Date.now() - timeOffsetMinutes * 60 * 1000),
    grid,
    tempMin,
    tempMax,
  };
}

export const GP2_STATION = {
  lat: 32.232333,
  lon: -9.251556,
  name: 'GP2',
};

export const GP1_STATION = {
  lat: 32.235333, // Légèrement au nord de GP2
  lon: -9.248556,
  name: 'GP1',
};