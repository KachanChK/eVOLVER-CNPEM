<script setup>
import { computed } from 'vue'
import { Chart, LineElement, LinearScale, PointElement, Tooltip } from 'chart.js'
import { Line } from 'vue-chartjs'

Chart.register(LineElement, LinearScale, PointElement, Tooltip)

const props = defineProps({
  readings: { type: Array, required: true },
  title: { type: String, default: 'Temperatura' },
  valueKey: { type: String, default: 'temperature_celsius' },
  unit: { type: String, default: ' °C' },
})
const dateTime = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'medium' })
const axisTime = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit', second: '2-digit',
})
const degrees = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 })
const latest = computed(() => props.readings.at(-1))
const data = computed(() => ({
  datasets: [{
    data: props.readings.map((reading) => ({
      x: Date.parse(reading.generated_at),
      y: reading[props.valueKey],
    })),
    borderColor: '#0062c7',
    backgroundColor: '#0062c7',
    borderWidth: 2,
    pointRadius: props.readings.length > 30 ? 0 : 3,
  }],
}))
const options = computed(() => {
  const firstTime = Date.parse(props.readings[0]?.generated_at)
  const lastTime = Date.parse(latest.value?.generated_at)
  return {
    animation: false,
    maintainAspectRatio: false,
    interaction: { mode: 'nearest', intersect: false },
    scales: {
      x: {
        type: 'linear',
        ...(firstTime === lastTime ? { min: firstTime - 30_000, max: firstTime + 30_000 } : {}),
        ticks: { maxTicksLimit: 5, maxRotation: 0, callback: (value) => axisTime.format(value) },
        grid: { display: false },
      },
      y: { grace: '5%', ticks: { callback: (value) => `${degrees.format(value)}${props.unit}` } },
    },
    plugins: {
      tooltip: {
        callbacks: {
          title: ([point]) => dateTime.format(point.parsed.x),
          label: (point) => `${degrees.format(point.parsed.y)}${props.unit}`,
        },
      },
    },
  }
})
</script>

<template>
  <section class="panel temperature" :aria-label="title">
    <h2>{{ title }}</h2>
    <template v-if="latest">
      <div class="latest">
        <strong>{{ degrees.format(latest[valueKey]) }}{{ unit }}</strong>
        <span>Última leitura · {{ dateTime.format(new Date(latest.generated_at)) }}</span>
      </div>
      <div class="chart">
        <Line :data="data" :options="options" :aria-label="`Gráfico de ${title} ao longo do tempo`" />
      </div>
      <details>
        <summary>Ver leituras ({{ readings.length }})</summary>
        <div class="table-scroll" tabindex="0" role="region" aria-label="Leituras de temperatura">
          <table>
            <thead><tr><th scope="col">Gerada em</th><th scope="col">Recebida em</th><th scope="col">{{ title }}</th></tr></thead>
            <tbody>
              <tr v-for="reading in readings" :key="`${reading.event_id}-${reading.generated_at}`">
                <td>{{ dateTime.format(new Date(reading.generated_at)) }}</td>
                <td>{{ dateTime.format(new Date(reading.received_at)) }}</td>
                <td>{{ degrees.format(reading[valueKey]) }}{{ unit }}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </details>
    </template>
    <p v-else class="muted">Nenhuma leitura registrada.</p>
  </section>
</template>
