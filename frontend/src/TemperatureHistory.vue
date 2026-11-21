<script setup>
import { computed, ref, watch } from 'vue'
import { Chart, LineElement, LinearScale, PointElement, Tooltip } from 'chart.js'
import { Line } from 'vue-chartjs'
import { chartPoints, missingIntervals, movingAverage, readingAge, readingPoints, timeStep } from './history.js'

Chart.register(LineElement, LinearScale, PointElement, Tooltip)

const props = defineProps({
  readings: { type: Array, required: true },
  liveReadings: { type: Array, required: true },
  window: { type: Object, required: true },
  now: { type: Number, required: true },
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
const points = computed(() => readingPoints(props.readings, props.valueKey))
const visible = computed(() => points.value.filter(point => point.x >= props.window.min && point.x <= props.window.max))
const latest = computed(() => points.value.at(-1))
const liveReceived = computed(() => props.liveReadings.reduce((last, reading) => {
  const time = Date.parse(reading.received_at ?? reading.generated_at)
  return Number.isFinite(time) ? Math.max(last, time) : last
}, -Infinity))
const freshness = computed(() => readingAge(liveReceived.value, props.now))
const stale = computed(() => props.now - liveReceived.value > 15_000)
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

const gapPlugin = {
  id: 'missing-readings',
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
      grace: '8%',
      ticks: { maxTicksLimit: 6, color: '#465365', font: { size: 13 }, callback: value => degrees.format(value) },
      title: { display: true, text: props.unit.trim() || props.title, color: '#465365', font: { size: 13 } },
      grid: { color: '#e6eaf0' },
      afterFit: scale => { scale.width = 76 },
    },
  },
  plugins: {
    tooltip: { callbacks: {
      title: ([point]) => dateTime.format(point.parsed.x),
      label: point => `${point.dataset.label}: ${degrees.format(point.parsed.y)}${props.unit}`,
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
          <strong>{{ latest ? degrees.format(latest.y) + unit : '—' }}</strong>
          <span v-if="latest">{{ paused ? 'Leitura exibida' : 'Último valor' }} · {{ dateTime.format(latest.x) }}</span>
        </div>
      </div>
      <p :class="['freshness', { stale }]">{{ freshness }}</p>
    </div>
    <div class="chart-legend">
      <span><i class="legend-line" aria-hidden="true"></i> Leituras</span>
      <span v-if="showAverage"><i class="legend-average" aria-hidden="true"></i> Média de 5 s</span>
      <span v-if="gaps.length"><i class="legend-gap" aria-hidden="true"></i> Sem leituras</span>
    </div>
    <div v-if="visible.length" class="chart">
      <Line :data="data" :options="options" :plugins="[gapPlugin]" :aria-label="`Gráfico de ${title}. ${visible.length} leituras no período selecionado. ${gaps.length ? 'Há períodos sem leituras.' : ''}`" />
    </div>
    <div v-else class="chart-empty">
      <strong>Sem leituras neste período</strong>
      <p>Escolha um período maior ou aguarde novas medições.</p>
    </div>
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
                <td>{{ degrees.format(point.y) }}{{ unit }}</td>
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
