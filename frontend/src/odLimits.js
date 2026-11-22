const MAX_OD_SCALE = 16_383

function trimTrailingZeros(digits) {
  let end = digits.length
  while (digits[end - 1] === '0') end--
  return digits.slice(0, end)
}

function readLimit(text) {
  if (!text) return { error: 'Informe este limite de OD.' }
  const parts = /^(\d+),(\d+)$/.exec(text)
  if (!parts) return { error: 'Use um decimal com vírgula, como 0,125.' }

  const [, integer, decimals] = parts
  // Ordering the fractional digits as text is exact once trailing zeros are removed.
  const fraction = trimTrailingZeros(decimals)
  if (!/^0+$/.test(integer) || fraction < '1' || fraction > '8') {
    return { error: 'Informe um valor entre 0,10 e 0,80.' }
  }
  if (fraction.length > MAX_OD_SCALE) {
    return { error: 'Informe até 16.383 casas decimais significativas.' }
  }
  return { error: '', fraction }
}

export function parseOdLimits({ od_min, od_max }) {
  const minimum = readLimit(od_min)
  const maximum = readLimit(od_max)
  const errors = { od_min: minimum.error, od_max: maximum.error }
  if (!errors.od_min && !errors.od_max && minimum.fraction >= maximum.fraction) {
    errors.od_max = 'Informe um valor maior que a OD mínima.'
  }
  return { errors, minimum: minimum.fraction, maximum: maximum.fraction }
}

export function encodeExperiment(fields, { minimum, maximum }) {
  // The validated fractions are digit-only. Write JSON number tokens without Number rounding.
  const experiment = JSON.stringify(fields)
  return `${experiment.slice(0, -1)},"od_min":0.${minimum},"od_max":0.${maximum}}`
}

function formatOdLimit(value) {
  const [integer, decimals = ''] = String(value).split('.')
  return `${integer},${trimTrailingZeros(decimals).padEnd(2, '0')}`
}

export function formatOdLimits({ od_min, od_max }) {
  if (od_min == null || od_max == null) return 'Não informados'
  return `${formatOdLimit(od_min)} a ${formatOdLimit(od_max)}`
}
