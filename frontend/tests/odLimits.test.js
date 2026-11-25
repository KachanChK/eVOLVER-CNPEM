import assert from 'node:assert/strict'
import { test } from 'node:test'
import { encodeExperiment, formatOdInput, formatOdLimits, parseOdLimits } from '../src/odLimits.js'

test('adds the decimal comma and limits OD input to three decimal places without rounding', () => {
  for (const [input, formatted] of [
    ['', ''],
    ['0', '0,'],
    ['1', '0,1'],
    ['17', '0,17'],
    ['017', '0,17'],
    ['64', '0,64'],
    [' 0.64 ', '0,64'],
    [',17', '0,17'],
    ['0,,17', '0,17'],
    ['0,.64', '0,64'],
    ['0,1234', '0,123'],
    ['0.7999', '0,799'],
    ['07999', '0,799'],
  ]) {
    assert.equal(formatOdInput(input), formatted)
  }
  assert.equal(formatOdInput('0', true), '')
  assert.equal(formatOdInput('0,', true), '0,')
})

test('rejects letters, signs and malformed separators in OD input', () => {
  for (const input of ['x', '0,17x', '0,1 7', '-0,125', '1e-1', '0,1.7']) {
    assert.equal(formatOdInput(input), null)
  }
})

test('accepts comma decimals including the endpoints and sends numbers', () => {
  for (const [minimum, maximum, expected] of [
    ['0,10', '0,80', ['0.1', '0.8']],
    ['0,125', '0,7', ['0.125', '0.7']],
    ['0,123456789', '0,7654321', ['0.123456789', '0.7654321']],
    ['0,1000000000000000000000000000000001', '0,1000000000000000000000000000000002',
      ['0.1000000000000000000000000000000001', '0.1000000000000000000000000000000002']],
  ]) {
    const limits = parseOdLimits({ od_min: minimum, od_max: maximum })
    assert.deepEqual(limits.errors, { od_min: '', od_max: '' })
    const body = encodeExperiment({ name: 'Nome com "aspas"', vial_id: 2 }, limits)
    assert.equal(body, `{"name":"Nome com \\"aspas\\"","vial_id":2,"od_min":${expected[0]},"od_max":${expected[1]}}`)
    assert.equal(typeof JSON.parse(body).od_min, 'number')
    assert.equal(typeof JSON.parse(body).od_max, 'number')
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
    ['0,0999999999999999999', /entre 0,10 e 0,80/],
    ['0,8000000000000000001', /entre 0,10 e 0,80/],
    [`0,1${'0'.repeat(16_382)}1`, /até 16\.383 casas/],
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
  for (const maximum of ['0,1000000000000000001', '0,10000000000000000020']) {
    const { errors } = parseOdLimits({ od_min: '0,1000000000000000002', od_max: maximum })
    assert.match(errors.od_max, /maior que a OD mínima/)
  }
})

test('formats OD limits in pt-BR and identifies legacy experiments', () => {
  assert.equal(formatOdLimits({ od_min: '0.1', od_max: '0.8' }), '0,10 a 0,80')
  assert.equal(formatOdLimits({ od_min: '0.125', od_max: '0.7' }), '0,125 a 0,70')
  assert.equal(
    formatOdLimits({ od_min: '0.1000000000000000001', od_max: '0.1000000000000000002' }),
    '0,1000000000000000001 a 0,1000000000000000002',
  )
  assert.equal(formatOdLimits({ od_min: null, od_max: null }), 'Não informados')
})
