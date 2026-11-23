import assert from 'node:assert/strict'
import test from 'node:test'
import { isFinal, isOld, pumpPeriods } from '../src/pumpHistory.js'

test('confirmed ON and paused periods are independent and clipped to the graph', () => {
  const transition = (second, paused, confirmed_state) => ({
    observed_at: new Date(second * 1000).toISOString(), paused, confirmed_state,
  })
  const transitions = [
    transition(1, false, 'off'),
    transition(2, false, 'on'),
    transition(4, true, 'on'),
    transition(5, true, 'unknown'),
    transition(8, false, 'off'),
  ]
  const periods = pumpPeriods(transitions, { min: 3000, max: 7000 })
  assert.deepEqual(periods.map(period => [
    period.start, period.end, period.paused, period.confirmed_state,
  ]), [
    [3000, 4000, false, 'on'],
    [4000, 5000, true, 'on'],
    [5000, 7000, true, 'unknown'],
  ])
})

test('receipt is still pending and result age starts after 10 seconds', () => {
  assert.equal(isFinal({ result_status: 'received' }), false)
  assert.equal(isFinal({ result_status: 'executed' }), true)
  assert.equal(isOld('1970-01-01T00:00:00Z', 10_000), false)
  assert.equal(isOld('1970-01-01T00:00:00Z', 10_001), true)
})
