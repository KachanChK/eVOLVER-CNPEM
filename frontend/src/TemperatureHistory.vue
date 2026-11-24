<script setup>
import { computed, ref, watch } from 'vue'
import { Chart, LineElement, LinearScale, PointElement, Tooltip } from 'chart.js'
import { Line } from 'vue-chartjs'
import { chartPoints, latestGeneratedAt, missingIntervals, movingAverage, readingAge, readingPoints, timeStep } from './history.js'

import { commandAction, commandStatus, isFinal, odValue, pumpPeriods, pumpTime } from './pumpHistory.js'
import { formatOdLimits } from './odLimits.js'

Chart.register(LineElement, LinearScale, PointElement, Tooltip)

const props = defineProps({
  readings: { type: Array, required: true },
  liveReadings: { type: Array, required: true },
  window: { type: Object, required: true },
  now: { type: Number, required: true },
  odLimits: { type: Object, default: null },
  pumpHistory: { type: Object, default: null },
  paused: Boolean,
  showAverage: Boolean,
  title: { type: String, default: 'Temperatura' },
  valueKey: { type: String, default: 'temperature_celsius' },
  unit: { type: String, default: ' °C' },
  color: { type: String, default: '#0062c7' },
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
const points = computed(() => readingPoints(props.readings, props.valueKey))
const visible = computed(() => points.value.filter(point => point.x >= props.window.min && point.x <= props.window.max))
const latest = computed(() => points.value.at(-1))
const liveGenerated = computed(() => latestGeneratedAt(props.liveReadings))
const freshness = computed(() => readingAge(liveGenerated.value, props.now))
const stale = computed(() => Number.isFinite(liveGenerated.value) && props.now - liveGenerated.value > 15_000)
const gaps = computed(() => missingIntervals(visible.value, props.window))
const drawn = computed(() => chartPoints(visible.value))
const reduced = computed(() => drawn.value.filter(point => point.y !== null).length < visible.value.length)
const tableOpen = ref(false)
const page = ref(1)
const pageCount = computed(() => Math.max(1, Math.ceil(visible.value.length / 50)))
const rows = computed(() => {
  const end = visible.value.length - (page.value - 1) * 50
  return visible.value.slice(Math.max(0, end - 50), end).toReversed()
})
watch(() => props.window, () => { page.value = 1 })

const data = computed(() => {
  const raw = {
    label: 'Leituras', data: drawn.value, borderColor: props.color, backgroundColor: props.color,
    borderWidth: 2,
    pointRadius: context => {
      const index = context.dataIndex
      const series = context.dataset.data
      const isolated = series[index]?.y !== null && series[index - 1]?.y == null && series[index + 1]?.y == null
      return visible.value.length <= 30 || isolated ? 3 : 0
    },
    pointHoverRadius: 5, pointHitRadius: 12, spanGaps: false, tension: 0,
  }
  if (!props.showAverage) return { datasets: [raw] }
  const averageWindow = points.value.filter(point => point.x >= props.window.min - 5_000 && point.x <= props.window.max)
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
        ctx.font = '13px system-ui'
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
        maxTicksLimit: 5, maxRotation: 0, color: '#465365', font: { size: 13 },
        stepSize: timeStep(props.window.max - props.window.min), includeBounds: false,
        callback: value => (props.window.max - props.window.min >= 86_400_000 ? axisDate : axisTime).format(value),
      },
      title: { display: true, text: 'Horário', color: '#465365', font: { size: 13 } },
      grid: { display: false },
    },
    y: {
      grace: '8%', suggestedMin: limits.value[0], suggestedMax: limits.value[1],
      ticks: { maxTicksLimit: 6, color: '#465365', font: { size: 13 }, callback: value => degrees.format(value) },
      title: { display: true, text: props.unit.trim() || props.title, color: '#465365', font: { size: 13 } },
      grid: { color: '#e6eaf0' },
      afterFit: scale => { scale.width = 76 },
    },
  },
  plugins: {
    tooltip: { callbacks: {
      title: ([point]) => dateTime.format(point.parsed.x),
      label: point => `${point.dataset.label}: ${number.value.format(point.parsed.y)}${props.unit}`,
    } },
  },
}))
</script>

<template>
  <section class="panel measurement" :aria-label="title" :style="{ '--measurement-color': color }">
    <div class="measurement-header">
      <div>
        <h2>{{ title }}</h2>
        <div class="latest">
          <strong>{{ latest ? number.format(latest.y) + unit : '—' }}</strong>
          <span v-if="latest">{{ paused ? 'Leitura exibida' : 'Último valor' }} · {{ dateTime.format(latest.x) }}</span>
        </div>
      </div>
      <p :class="['freshness', { stale }]">{{ freshness }}</p>
    </div>
    <div class="chart-legend">
      <span><i class="legend-line" aria-hidden="true"></i> Leituras</span>
      <span v-if="showAverage"><i class="legend-average" aria-hidden="true"></i> Média de 5 s</span>
      <span v-if="gaps.length"><i class="legend-gap" aria-hidden="true"></i> Sem leituras</span>
      <template v-if="odLimits">
        <span v-if="limits.length"><i class="legend-average" aria-hidden="true"></i> Limites de OD ({{ formatOdLimits(odLimits) }})</span>
        <span><i class="legend-on" aria-hidden="true"></i> Bombas ligadas com confirmação</span>
        <span><i class="legend-paused" aria-hidden="true"></i> Automação pausada</span>
        <span><i class="legend-intent" aria-hidden="true"></i> Intenção de comando</span>
        <span><i class="legend-result" aria-hidden="true"></i> Resultado registrado</span>
      </template>
    </div>
    <div v-if="visible.length || limits.length || periods.length || commands.length" class="chart">
      <Line :data="data" :options="options" :plugins="[annotations]" :aria-label="`Gráfico de ${title}. ${visible.length} leituras no período selecionado. ${gaps.length ? 'Há períodos sem leituras.' : ''}`" />
    </div>
    <div v-else class="chart-empty">
      <strong>Sem leituras neste período</strong>
      <p>Escolha um período maior ou aguarde novas medições.</p>
    </div>
    <details v-if="periods.length || commands.length" class="pump-history">
      <summary>Ver períodos e comandos das bombas</summary>
      <ul v-if="periods.length">
        <li v-for="(interval, index) in periods" :key="index">
          {{ pumpTime.format(interval.start) }} a {{ pumpTime.format(interval.end) }}
          · {{ interval.paused ? 'Automação pausada' : 'Automação ativa' }}
          <template v-if="interval.confirmed_state === 'on'"> · Bombas ligadas com confirmação</template>
        </li>
      </ul>
      <div v-if="commands.length" class="table-scroll" tabindex="0" role="region" aria-label="Comandos das bombas">
        <table>
          <thead><tr><th scope="col">Comando</th><th scope="col">Intenção</th><th scope="col">Resultado</th></tr></thead>
          <tbody>
            <tr v-for="command in commands" :key="command.command_id">
              <td><code translate="no">{{ command.command_id }}</code></td>
              <td>{{ commandAction(command) }} · {{ pumpTime.format(new Date(command.created_at)) }}</td>
              <td>
                {{ commandStatus[command.result_status] ?? command.result_status }}
                <template v-if="command.result_at"> · {{ pumpTime.format(new Date(command.result_at)) }}</template>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </details>
    <p v-if="reduced" class="chart-note">Exibição resumida, com os maiores e menores valores preservados. Todas as leituras estão na tabela.</p>
    <details @toggle="tableOpen = $event.target.open">
      <summary>Ver leituras do período ({{ visible.length }})</summary>
      <template v-if="tableOpen">
        <div class="table-scroll" tabindex="0" role="region" :aria-label="`Leituras de ${title}`">
          <table>
            <thead><tr><th scope="col">Gerada em</th><th scope="col">Recebida em</th><th scope="col">{{ title }}</th></tr></thead>
            <tbody>
              <tr v-for="point in rows" :key="`${point.reading.event_id}-${point.x}`">
                <td>{{ dateTime.format(point.x) }}</td>
                <td>{{ dateTime.format(new Date(point.reading.received_at)) }}</td>
                <td>{{ number.format(point.y) }}{{ unit }}</td>
              </tr>
            </tbody>
          </table>
        </div>
        <nav v-if="pageCount > 1" class="table-pages" :aria-label="`Páginas das leituras de ${title}`">
          <button :disabled="page === 1" @click="page--">Mais recentes</button>
          <span>Página {{ page }} de {{ pageCount }}</span>
          <button :disabled="page === pageCount" @click="page++">Mais antigas</button>
        </nav>
      </template>
    </details>
  </section>
</template>
