import assert from 'node:assert/strict'
import test from 'node:test'
import { chartPoints, historyWindow, missingIntervals, movingAverage, readingAge, readingPoints, reducePoints, timeStep } from '../src/history.js'

const now = Date.parse('2026-11-17T12:00:00Z')
const reading = (offset, value) => ({ generated_at: new Date(now + offset).toISOString(), value })

test('time labels use regular seconds, minutes and days', () => {
  assert.equal(timeStep(60_000), 15_000)
  assert.equal(timeStep(300_000), 60_000)
  assert.equal(timeStep(1_800_000), 600_000)
  assert.equal(timeStep(10 * 86_400_000), 2 * 86_400_000)
})

test('periods share a clock, include quiet time and keep ended experiments visible', () => {
  const series = [[reading(-120_000, 37)], [reading(-600_000, 7)], []]
  for (const duration of [60_000, 300_000, 1_800_000]) {
    assert.deepEqual(historyWindow(series, duration, now), { min: now - duration, max: now })
  }
  assert.deepEqual(historyWindow(series, null, now), { min: now - 600_000, max: now })
  assert.deepEqual(historyWindow(series, 60_000, now + 86_400_000, new Date(now).toISOString()), { min: now - 60_000, max: now })
  assert.equal(historyWindow([[]], null, now).max - historyWindow([[]], null, now).min, 1000)
})

test('points are sorted without changing the originals and invalid values are excluded', () => {
  const source = [reading(1000, 2), reading(0, 1), reading(2000, null), { generated_at: 'invalid', value: 3 }]
  const copy = structuredClone(source)
  assert.deepEqual(readingPoints(source, 'value').map(p => p.y), [1, 2])
  assert.deepEqual(source, copy)
})

test('gaps break the line instead of inventing an uninterrupted trend', () => {
  const points = [{ x: 0, y: 1 }, { x: 500, y: 2 }, { x: 60_000, y: 3 }, { x: 60_500, y: 4 }]
  const drawn = chartPoints(points)
  assert.deepEqual(drawn.map(p => p.y), [1, 2, null, 3, 4])
  assert.ok(drawn[2].x > 500 && drawn[2].x < 60_000)
  assert.deepEqual(missingIntervals(points, { min: 0, max: 70_000 }), [
    { start: 500, end: 60_000 }, { start: 60_500, end: 70_000 },
  ])
  assert.deepEqual(missingIntervals([], { min: 0, max: 60_000 }), [{ start: 0, end: 60_000 }])
})

test('large histories keep spikes, troughs, endpoints and chronological order', () => {
  const points = Array.from({ length: 10_000 }, (_, i) => ({ x: i * 500, y: Math.sin(i) }))
  points[241].y = 90
  points[9234].y = -80
  const before = structuredClone(points)
  const reduced = reducePoints(points)
  assert.ok(reduced.length <= 800)
  assert.equal(reduced[0], points[0])
  assert.equal(reduced.at(-1), points.at(-1))
  assert.ok(reduced.includes(points[241]) && reduced.includes(points[9234]))
  assert.ok(reduced.every((point, i) => i === 0 || point.x > reduced[i - 1].x))
  assert.deepEqual(points, before)
})

test('reducing a large history still preserves every gap and isolated reading', () => {
  const first = Array.from({ length: 3000 }, (_, i) => ({ x: i * 500, y: 2 }))
  const second = Array.from({ length: 3000 }, (_, i) => ({ x: 2_000_000 + i * 500, y: 3 }))
  const drawn = chartPoints([...first, { x: 1_800_000, y: 99 }, ...second])
  assert.equal(drawn.filter(p => p.y === null).length, 2)
  assert.ok(drawn.some(p => p.x === 1_800_000 && p.y === 99))
  assert.ok(drawn.length < 810)
})

test('the optional average is based on elapsed time and resets after gaps', () => {
  const points = [{ x: 0, y: 2 }, { x: 500, y: 4 }, { x: 5000, y: 6 }, { x: 5500, y: 8 }, { x: 20_000, y: 20 }]
  assert.deepEqual(movingAverage(points).map(p => p.y), [2, 3, 4, 6, 20])
  assert.equal(chartPoints(movingAverage(points)).filter(p => p.y === null).length, 1)
  assert.equal(points.at(-1).y, 20)
})

test('freshness handles missing data, clock differences and long interruptions', () => {
  assert.equal(readingAge(-Infinity, now), 'Ainda sem leituras')
  assert.equal(readingAge(now + 1000, now), 'Última leitura recebida agora')
  assert.equal(readingAge(now - 15_000, now), 'Última leitura recebida há 15 s')
  assert.equal(readingAge(now - 180_000, now), 'Última leitura recebida há 3 min')
  assert.equal(readingAge(now - 86_400_000, now), 'Última leitura recebida há 1 dia(s)')
})
