<script setup>
import { computed } from 'vue'
import { Chart, Filler, LineElement, LinearScale, PointElement, Tooltip } from 'chart.js'
import { Line } from 'vue-chartjs'
import { chartPoints, missingIntervals, movingAverage, timeStep } from './history.js'

import { isFinal, odValue, pumpPeriods } from './pumpHistory.js'
import { formatOdLimits } from './odLimits.js'
import limitsIcon from './assets/limits.svg'

Chart.register(Filler, LineElement, LinearScale, PointElement, Tooltip)

const props = defineProps({
  points: { type: Array, required: true },
  window: { type: Object, required: true },
  odLimits: { type: Object, default: null },
  pumpHistory: { type: Object, default: null },
  showAverage: Boolean,
  title: { type: String, required: true },
  unit: { type: String, required: true },
  color: { type: String, required: true },
  icon: { type: String, required: true },
})
const dateTime = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'medium' })
const axisTime = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const axisDate = new Intl.DateTimeFormat('pt-BR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
const degrees = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 })
const number = computed(() => props.odLimits ? odValue : degrees)
const limits = computed(() => [props.odLimits?.od_min, props.odLimits?.od_max]
  .filter(value => value != null).map(Number))
const periods = computed(() => pumpPeriods(props.pumpHistory?.transitions ?? [], props.window))
const inWindow = time => {
  const at = Date.parse(time)
  return at >= props.window.min && at <= props.window.max
}
const commands = computed(() => (props.pumpHistory?.commands ?? [])
  .filter(command => inWindow(command.created_at) || (isFinal(command) && inWindow(command.result_at))))
const visible = computed(() => props.points.filter(point => point.x >= props.window.min && point.x <= props.window.max))
const gaps = computed(() => missingIntervals(visible.value, props.window))
const drawn = computed(() => chartPoints(visible.value))
const reduced = computed(() => drawn.value.filter(point => point.y !== null).length < visible.value.length)
const extremes = computed(() => {
  if (!visible.value.length) return null
  let low = visible.value[0]
  let high = low
  for (const point of visible.value) {
    if (point.y < low.y) low = point
    if (point.y > high.y) high = point
  }
  return { low, high }
})

const data = computed(() => {
  const raw = {
    label: 'Leituras', data: drawn.value, borderColor: props.color, backgroundColor: `${props.color}18`,
    fill: 'start', pointBackgroundColor: props.color, pointBorderColor: '#fff',
    borderWidth: 2,
    pointRadius: context => {
      const index = context.dataIndex
      const series = context.dataset.data
      const point = series[index]
      if (!point || point.y === null) return 0
      if ([extremes.value?.low, extremes.value?.high].some(extreme => extreme?.x === point.x && extreme.y === point.y)) return 4
      const isolated = series[index - 1]?.y == null && series[index + 1]?.y == null
      return visible.value.length <= 30 || isolated ? 3 : 0
    },
    pointHoverRadius: 5, pointHitRadius: 12, spanGaps: false, tension: 0,
  }
  if (!props.showAverage) return { datasets: [raw] }
  const averageWindow = props.points.filter(point => point.x >= props.window.min - 5_000 && point.x <= props.window.max)
  const average = {
    label: 'Média de 5 s', data: chartPoints(movingAverage(averageWindow).filter(point => point.x >= props.window.min)),
    borderColor: '#48566a', borderWidth: 2, borderDash: [6, 4],
    pointRadius: 0, pointHoverRadius: 4, spanGaps: false, tension: 0,
  }
  return { datasets: [raw, average] }
})

const annotations = {
  id: 'history-annotations',
  beforeDatasetsDraw(chart) {
    const { ctx, chartArea, scales } = chart
    ctx.save()
    ctx.beginPath()
    ctx.rect(chartArea.left, chartArea.top, chartArea.width, chartArea.height)
    ctx.clip()
    for (const gap of gaps.value) {
      const left = scales.x.getPixelForValue(gap.start)
      const right = scales.x.getPixelForValue(gap.end)
      ctx.fillStyle = '#edf1f5'
      ctx.fillRect(left, chartArea.top, right - left, chartArea.height)
      if (right - left > 100) {
        ctx.fillStyle = '#505d6d'
        ctx.font = '12px Roboto, sans-serif'
        ctx.textAlign = 'center'
        ctx.fillText('Sem leituras', (left + right) / 2, chartArea.top + 22)
      }
    }
    ctx.setLineDash([6, 4])
    ctx.strokeStyle = '#505d6d'
    for (const limit of limits.value) {
      const y = scales.y.getPixelForValue(limit)
      ctx.beginPath()
      ctx.moveTo(chartArea.left, y)
      ctx.lineTo(chartArea.right, y)
      ctx.stroke()
    }
    for (const period of periods.value) {
      const left = scales.x.getPixelForValue(period.start)
      const width = scales.x.getPixelForValue(period.end) - left
      if (period.paused) {
        ctx.fillStyle = '#99702c'
        ctx.fillRect(left, chartArea.bottom - 6, width, 6)
      }
      if (period.confirmed_state === 'on') {
        ctx.fillStyle = '#275b96'
        ctx.fillRect(left, chartArea.bottom - 13, width, 6)
      }
    }
    for (const command of commands.value) {
      if (inWindow(command.created_at)) {
        const x = scales.x.getPixelForValue(Date.parse(command.created_at))
        ctx.strokeStyle = '#7546b6'
        ctx.beginPath()
        ctx.moveTo(x, chartArea.top)
        ctx.lineTo(x, chartArea.top + 20)
        ctx.stroke()
      }
      if (isFinal(command) && inWindow(command.result_at)) {
        const x = scales.x.getPixelForValue(Date.parse(command.result_at))
        ctx.fillStyle = '#25465d'
        ctx.fillRect(x - 2, chartArea.top + 22, 4, 9)
      }
    }
    ctx.restore()
  },
}
const options = computed(() => ({
  animation: false,
  maintainAspectRatio: false,
  parsing: false,
  interaction: { mode: 'nearest', axis: 'x', intersect: false },
  layout: { padding: { top: 8, right: 8 } },
  scales: {
    x: {
      type: 'linear', min: props.window.min, max: props.window.max,
      ticks: {
        maxTicksLimit: 6, maxRotation: 0, color: '#505d6d', font: { size: 11, family: 'Roboto, sans-serif' },
        stepSize: timeStep(props.window.max - props.window.min), includeBounds: false,
        callback: value => (props.window.max - props.window.min >= 86_400_000 ? axisDate : axisTime).format(value),
      },
      grid: { display: false },
      border: { color: '#dce2eb' },
    },
    y: {
      grace: '8%', suggestedMin: limits.value[0], suggestedMax: limits.value[1],
      ticks: { maxTicksLimit: 5, color: '#505d6d', font: { size: 11, family: 'Roboto, sans-serif' }, callback: value => degrees.format(value) },
      grid: { color: '#e6eaf0' },
      border: { display: false },
    },
  },
  plugins: {
    tooltip: { callbacks: {
      title: ([point]) => dateTime.format(point.parsed.x),
      label: point => `${point.dataset.label}: ${number.value.format(point.parsed.y)} ${props.unit}`,
    } },
  },
}))
</script>

<template>
  <section class="panel measurement" :aria-label="`Histórico de ${title}`">
    <div class="measurement-header">
      <div>
        <h3>{{ title }}</h3>
        <p class="muted">{{ limits.length ? 'Faixa configurada: ' + formatOdLimits(odLimits) : 'Unidade: ' + unit }}</p>
      </div>
      <div class="chart-meta">
        <div class="chart-legend">
          <span><img :src="icon" alt="" width="7" height="7" /> Leituras</span>
          <span v-if="showAverage"><i class="legend-average" aria-hidden="true"></i> Média de 5 s</span>
          <span v-if="gaps.length && (visible.length || limits.length || periods.length || commands.length)"><i class="legend-gap" aria-hidden="true"></i> Sem leituras</span>
          <span v-if="limits.length"><img :src="limitsIcon" alt="" width="15" height="8" /> Limites</span>
        </div>
        <div v-if="extremes" class="chart-extremes">
          <span>Mín. {{ number.format(extremes.low.y) }}&nbsp;{{ unit }}</span>
          <span>Máx. {{ number.format(extremes.high.y) }}&nbsp;{{ unit }}</span>
        </div>
      </div>
    </div>
    <div v-if="visible.length || limits.length || periods.length || commands.length" class="chart">
      <Line :data="data" :options="options" :plugins="[annotations]" :aria-label="`Gráfico de ${title}. ${visible.length} leituras no período selecionado. ${gaps.length ? 'Há períodos sem leituras.' : ''}`" />
    </div>
    <div v-else class="chart-empty">
      <strong>Sem leituras neste período</strong>
      <p>Escolha um período maior ou aguarde novas medições.</p>
    </div>
    <div v-if="periods.length || commands.length" class="chart-legend pump-legend">
      <span v-if="periods.some(period => period.confirmed_state === 'on')"><i class="legend-on" aria-hidden="true"></i> Bombas ligadas com confirmação</span>
      <span v-if="periods.some(period => period.paused)"><i class="legend-paused" aria-hidden="true"></i> Automação pausada</span>
      <template v-if="commands.length">
        <span><i class="legend-intent" aria-hidden="true"></i> Intenção de comando</span>
        <span><i class="legend-result" aria-hidden="true"></i> Resultado registrado</span>
      </template>
    </div>
    <p v-if="reduced" class="chart-note">Exibição resumida, com os maiores e menores valores preservados. Todas as leituras estão na tabela.</p>
  </section>
</template>
