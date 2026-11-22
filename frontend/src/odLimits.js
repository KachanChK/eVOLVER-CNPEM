function validateLimit(text, value) {
  if (!text) return 'Informe este limite de OD.'
  if (!/^\d+,\d+$/.test(text)) return 'Use um decimal com vírgula, como 0,125.'

  if (!Number.isFinite(value) || value < 0.10 || value > 0.80) {
    return 'Informe um valor entre 0,10 e 0,80.'
  }
  return ''
}

export function parseOdLimits({ od_min, od_max }) {
  const values = {
    od_min: Number(od_min.replace(',', '.')),
    od_max: Number(od_max.replace(',', '.')),
  }

  const errors = {
    od_min: validateLimit(od_min, values.od_min),
    od_max: validateLimit(od_max, values.od_max),
  }

  if (!errors.od_min && !errors.od_max && values.od_min >= values.od_max) {
    errors.od_max = 'Informe um valor maior que a OD mínima.'
  }

  return { errors, values }
}

const odNumber = new Intl.NumberFormat('pt-BR', {
  minimumFractionDigits: 2,
  maximumFractionDigits: 17,
})

export function formatOdLimits({ od_min, od_max }) {
  if (od_min == null || od_max == null) return 'Não informados'
  return `${odNumber.format(od_min)} a ${odNumber.format(od_max)}`
}
