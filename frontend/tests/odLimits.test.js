import assert from 'node:assert/strict'
import { test } from 'node:test'
import { formatOdLimits, parseOdLimits } from '../src/odLimits.js'

test('accepts comma decimals including the endpoints and sends numbers', () => {
  for (const [minimum, maximum, expected] of [
    ['0,10', '0,80', [0.10, 0.80]],
    ['0,125', '0,7', [0.125, 0.7]],
    ['0,123456789', '0,7654321', [0.123456789, 0.7654321]],
  ]) {
    const { errors, values } = parseOdLimits({ od_min: minimum, od_max: maximum })
    assert.deepEqual(errors, { od_min: '', od_max: '' })
    assert.deepEqual(JSON.parse(JSON.stringify(values)), { od_min: expected[0], od_max: expected[1] })
  }
})

test('flags missing, malformed and out-of-range values at either field', () => {
  for (const [value, message] of [
    ['', /Informe este limite/],
    ['0.7', /decimal com vírgula/],
    ['1', /decimal com vírgula/],
    ['1e-1', /decimal com vírgula/],
    ['abc', /decimal com vírgula/],
    ['0,7x', /decimal com vírgula/],
    ['0,09', /entre 0,10 e 0,80/],
    ['0,81', /entre 0,10 e 0,80/],
    [`${'9'.repeat(400)},0`, /entre 0,10 e 0,80/],
  ]) {
    const { errors } = parseOdLimits({ od_min: value, od_max: value })
    assert.match(errors.od_min, message)
    assert.match(errors.od_max, message)
  }
})

test('requires a maximum strictly greater than the minimum', () => {
  for (const maximum of ['0,6', '0,5']) {
    const { errors } = parseOdLimits({ od_min: '0,60', od_max: maximum })
    assert.equal(errors.od_min, '')
    assert.match(errors.od_max, /maior que a OD mínima/)
  }
})

test('formats OD limits in pt-BR and identifies legacy experiments', () => {
  assert.equal(formatOdLimits({ od_min: 0.1, od_max: 0.8 }), '0,10 a 0,80')
  assert.equal(formatOdLimits({ od_min: 0.125, od_max: 0.7 }), '0,125 a 0,70')
  assert.equal(formatOdLimits({ od_min: 0.123456789, od_max: 0.7 }), '0,123456789 a 0,70')
  assert.equal(formatOdLimits({ od_min: null, od_max: null }), 'Não informados')
})
