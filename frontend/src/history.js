// Each measurement arrives every 500 ms. Pauses over 5 s are shown as gaps.
export const GAP_MS = 5_000
export const PERIODS = [
  { label: '1 min', value: 60_000 },
  { label: '5 min', value: 300_000 },
  { label: '30 min', value: 1_800_000 },
  { label: 'Todo o tempo', value: null },
]

export function timeStep(duration) {
  const steps = [1_000, 5_000, 10_000, 15_000, 30_000, 60_000, 120_000, 300_000,
    600_000, 900_000, 1_800_000, 3_600_000, 7_200_000, 21_600_000, 43_200_000, 86_400_000]
  return steps.find(step => step >= duration / 5) ?? Math.ceil(duration / 5 / 86_400_000) * 86_400_000
}

export function historyWindow(series, duration, now, endedAt, startedAt) {
  const end = Number.isFinite(Date.parse(endedAt)) ? Date.parse(endedAt) : now
  const start = Date.parse(startedAt)
  let first = Number.isFinite(start) ? Math.min(start, end) : end
  for (const readings of series) {
    for (const reading of readings) {
      const time = Date.parse(reading.generated_at)
      if (Number.isFinite(time)) first = Math.min(first, time)
    }
  }
  return { min: duration === null ? Math.min(first, end - 1_000) : end - duration, max: end }
}

export function readingPoints(readings, valueKey) {
  return readings.map(reading => ({ x: Date.parse(reading.generated_at), y: reading[valueKey], reading }))
    .filter(point => Number.isFinite(point.x) && Number.isFinite(point.y))
    .sort((a, b) => a.x - b.x)
}

export function latestGeneratedAt(readings) {
  return readings.reduce((latest, reading) => {
    const generated = Date.parse(reading.generated_at)
    return Number.isFinite(generated) ? Math.max(latest, generated) : latest
  }, -Infinity)
}

export function splitSegments(points, gap = GAP_MS) {
  const segments = []
  for (const point of points) {
    const segment = segments.at(-1)
    if (!segment || point.x - segment.at(-1).x > gap) segments.push([point])
    else segment.push(point)
  }
  return segments
}

// Keep real observations: both extremes and the first/last point of each bucket.
// Only the drawing changes; original readings and timestamps remain untouched.
export function reducePoints(points, budget = 800) {
  if (points.length <= budget) return points
  const size = Math.ceil(points.length / Math.max(1, Math.floor(budget / 4)))
  const selected = []
  for (let start = 0; start < points.length; start += size) {
    const end = Math.min(start + size, points.length) - 1
    let low = start
    let high = start
    for (let index = start + 1; index <= end; index++) {
      if (points[index].y < points[low].y) low = index
      if (points[index].y > points[high].y) high = index
    }
    for (const index of [...new Set([start, low, high, end])].sort((a, b) => a - b)) {
      selected.push(points[index])
    }
  }
  return selected
}

export function chartPoints(points, budget = 800) {
  const result = []
  for (const segment of splitSegments(points)) {
    if (result.length) result.push({ x: (result.at(-1).x + segment[0].x) / 2, y: null })
    const share = Math.max(4, Math.floor(budget * segment.length / points.length))
    result.push(...reducePoints(segment, share).map(({ x, y }) => ({ x, y })))
  }
  return result
}

export function missingIntervals(points, window) {
  const gaps = []
  let previous = window.min
  for (const point of points) {
    if (point.x - previous > GAP_MS) gaps.push({ start: previous, end: point.x })
    previous = point.x
  }
  if (window.max - previous > GAP_MS) gaps.push({ start: previous, end: window.max })
  return gaps
}

export function movingAverage(points, duration = 5_000) {
  const result = []
  for (const segment of splitSegments(points)) {
    let start = 0
    let sum = 0
    for (let index = 0; index < segment.length; index++) {
      const point = segment[index]
      sum += point.y
      while (segment[start].x < point.x - duration) sum -= segment[start++].y
      result.push({ x: point.x, y: sum / (index - start + 1) })
    }
  }
  return result
}

export function readingAge(timestamp, now) {
  if (!Number.isFinite(timestamp)) return 'Ainda sem leituras'
  const seconds = Math.max(0, Math.floor((now - timestamp) / 1_000))
  if (seconds < 2) return 'Última leitura gerada agora'
  if (seconds < 60) return `Última leitura gerada há ${seconds} s`
  if (seconds < 3_600) return `Última leitura gerada há ${Math.floor(seconds / 60)} min`
  const hours = Math.floor(seconds / 3_600)
  if (hours < 24) return `Última leitura gerada há ${hours} h`
  return `Última leitura gerada há ${Math.floor(hours / 24)} dia(s)`
}
