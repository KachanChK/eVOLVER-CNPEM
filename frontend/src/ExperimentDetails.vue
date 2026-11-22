<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef } from 'vue'
import { useRouter } from 'vue-router'
import { request } from './api'
import TemperatureHistory from './TemperatureHistory.vue'
import { historyWindow, PERIODS } from './history.js'
import { formatOdLimits } from './odLimits.js'

const props = defineProps({ id: { type: String, default: '' } })
const emit = defineEmits(['changed'])
const router = useRouter()
const experiment = ref(null)
const readings = ref([])
const phReadings = ref([])
const odReadings = ref([])
const loading = ref(false)
const error = ref('')
const actionError = ref('')
const pending = ref(false)
const heading = ref(null)
const period = ref(60_000)
const showAverage = ref(false)
const paused = shallowRef(null)
const now = ref(Date.now())
const viewTime = ref(Date.now())
const updateError = ref('')
const pumpStatus = {
  automatic: 'Bomba em modo automático',
  pausing: 'Pausando…',
  paused: 'Bomba pausada',
  off_unconfirmed: 'Desligamento não confirmado. O modo automático está pausado.',
  resuming: 'Despausando… Aguardando a confirmação do desligamento.',
  resume_off_unconfirmed: 'Desligamento não confirmado. Aguardando reconciliação.',
}
const pump = ref(null)
const pumpError = ref('')
const pendingPump = ref(false)
const pumpAction = computed(() => ['paused', 'pausing', 'off_unconfirmed'].includes(pump.value?.state)
  ? 'resume' : 'pause')
const liveSeries = computed(() => [readings.value, phReadings.value, odReadings.value])
const displayedSeries = computed(() => paused.value?.series ?? liveSeries.value)
const window = computed(() => historyWindow(
  displayedSeries.value,
  period.value,
  paused.value?.at ?? viewTime.value,
  paused.value ? paused.value.endedAt : experiment.value?.ended_at,
))
const rangeDate = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'medium' })
const rangeLabel = computed(() => `${rangeDate.format(window.value.min)} — ${rangeDate.format(window.value.max)}`)
function togglePause() {
  if (paused.value) {
    paused.value = null
    viewTime.value = Date.now()
  } else {
    paused.value = { series: liveSeries.value, at: viewTime.value, endedAt: experiment.value?.ended_at }
  }
}
const base = `/experiments/${encodeURIComponent(props.id)}`
const dateTime = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
let pollTimer
let clockTimer
let readingRequest = false
let pumpRequest = false
let disposed = false
let actionRevision = 0
let pumpRevision = 0

async function loadReadings() {
  if (readingRequest || pending.value) return
  readingRequest = true
  const revision = actionRevision
  try {
    const details = request(base).then((data) => {
      if (!disposed && revision === actionRevision) experiment.value = data
    })
    const [temperature, ph, od] = await Promise.all([
      request(`${base}/temperature-readings`),
      request(`${base}/readings/ph`),
      request(`${base}/readings/od`),
      details,
    ])
    if (disposed) return
    readings.value = temperature
    phReadings.value = ph
    odReadings.value = od
    updateError.value = ''
  } finally {
    readingRequest = false
    viewTime.value = Date.now()
  }
}

async function loadPump() {
  if (pumpRequest || pendingPump.value || pending.value || experiment.value?.status === 'inactive') return
  pumpRequest = true
  const revision = pumpRevision
  try {
    const state = await request(`${base}/pump`)
    if (disposed || revision !== pumpRevision) return
    pump.value = state
    pumpError.value = ''
  } catch {
    if (!disposed && revision === pumpRevision) {
      pumpError.value = 'Não foi possível atualizar o estado da bomba. A atualização será tentada novamente.'
    }
  } finally {
    pumpRequest = false
  }
}

async function load() {
  if (!props.id) return
  loading.value = true
  error.value = ''
  try {
    await loadReadings()
    await nextTick()
    heading.value?.focus({ preventScroll: true })
  } catch (failure) {
    error.value = failure.message
  } finally {
    loading.value = false
  }
}

async function change(action) {
  const deleting = action === 'delete'
  const confirmation = deleting
    ? 'Excluir este experimento da interface? O histórico será preservado no banco.'
    : 'Inativar este experimento e liberar o vial? O histórico continuará disponível.'
  if (!globalThis.confirm(confirmation)) return
  actionRevision++
  pumpRevision++
  pending.value = true
  actionError.value = ''
  try {
    if (deleting) {
      await request(base, { method: 'DELETE' })
      emit('changed', 'Experimento excluído da interface.')
      await router.replace({ name: 'home' })
    } else {
      experiment.value = await request(`${base}/inactivate`, { method: 'POST' })
      emit('changed', 'Experimento inativado. Vial liberado.')
    }
  } catch (failure) {
    actionError.value = failure.message
  } finally {
    pending.value = false
  }
}

async function changePumpMode() {
  pumpRevision++
  pendingPump.value = true
  pumpError.value = ''
  try {
    const state = await request(`${base}/pump/${pumpAction.value}`, { method: 'POST' })
    if (!disposed) pump.value = state
  } catch (failure) {
    if (!disposed) pumpError.value = failure.message
  } finally {
    pendingPump.value = false
  }
}

onMounted(() => {
  load()
  if (props.id) {
    loadPump()
    pollTimer = setInterval(() => {
      loadPump()
      loadReadings().catch(() => { updateError.value = 'Não foi possível atualizar as leituras. Exibindo os últimos dados recebidos.' })
    }, 5000)
  }
  clockTimer = setInterval(() => { now.value = Date.now() }, 1000)
})
onUnmounted(() => {
  disposed = true
  clearInterval(pollTimer)
  clearInterval(clockTimer)
})
</script>

<template>
  <section v-if="!id" class="panel empty">
    <h1>Experimentos</h1>
    <p class="muted">Selecione um experimento no menu para ver suas leituras.</p>
  </section>
  <p v-else-if="loading" role="status">Carregando experimento…</p>
  <div v-else-if="error" class="panel" role="alert">
    <p>{{ error }}</p>
    <button @click="load">Tentar novamente</button>
  </div>
  <template v-else-if="experiment">
    <header class="detail-header">
      <div>
        <p class="meta">Vial {{ experiment.vial_id }} · {{ experiment.status === 'active' ? 'Ativo' : 'Inativo' }}</p>
        <h1 ref="heading" tabindex="-1">{{ experiment.name }}</h1>
        <p class="muted">Tipo de cultura · {{ experiment.culture_type ?? 'Não informado' }}</p>
        <p class="muted">Limites de OD · {{ formatOdLimits(experiment) }}</p>
        <p class="muted">Início · {{ dateTime.format(new Date(experiment.started_at)) }}</p>
        <p v-if="experiment.ended_at" class="muted">Fim · {{ dateTime.format(new Date(experiment.ended_at)) }}</p>
      </div>
      <div class="actions">
        <button v-if="experiment.status === 'active'" :disabled="pending || pendingPump" @click="change('inactivate')">Inativar</button>
        <button class="danger" :disabled="pending || pendingPump" @click="change('delete')">Excluir</button>
      </div>
    </header>
    <p v-if="actionError" class="error" role="alert">{{ actionError }}</p>
    <section v-if="experiment.status === 'active' && !pump?.ending"
      class="pump-controls panel" aria-label="Controle da bomba">
      <button v-if="pump" type="button" :disabled="pending || pendingPump" @click="changePumpMode">
        {{ pumpAction === 'pause' ? 'Pausar bomba' : 'Despausar bomba' }}
      </button>
      <p :class="pump?.state.endsWith('off_unconfirmed') ? 'danger' : 'muted'" role="status">
        {{ pump ? pumpStatus[pump.state] : pumpError ? '' : 'Consultando estado da bomba…' }}
      </p>
      <p v-if="pumpError" class="error" role="alert">{{ pumpError }}</p>
    </section>
    <section class="history-controls panel" aria-label="Controles dos gráficos">
      <div class="history-toolbar">
        <div>
          <span class="control-label" id="period-label">Período dos três gráficos</span>
          <div class="period-buttons" role="group" aria-labelledby="period-label">
            <button v-for="choice in PERIODS" :key="choice.label" :aria-pressed="period === choice.value"
              @click="period = choice.value">{{ choice.label }}</button>
          </div>
        </div>
        <button class="pause-button" :aria-pressed="!!paused" @click="togglePause">
          {{ paused ? 'Retomar visualização' : 'Pausar visualização' }}
        </button>
      </div>
      <div class="history-toolbar history-secondary">
        <p :class="['view-status', { paused }]" role="status">
          {{ paused ? 'Visualização pausada. A coleta de dados continua.' : experiment.status === 'active' ? 'Acompanhando agora · atualização a cada 5 s' : 'Histórico do experimento encerrado' }}
        </p>
        <label class="average-toggle"><input v-model="showAverage" type="checkbox"> Mostrar média de 5 s</label>
      </div>
      <p class="muted history-range">{{ rangeLabel }}</p>
    </section>
    <p v-if="updateError" class="notice" role="alert">{{ updateError }}</p>
    <div class="history-panels">
      <TemperatureHistory :readings="displayedSeries[0]" :live-readings="readings" :window="window" :now="now" :paused="!!paused" :show-average="showAverage" />
      <TemperatureHistory :readings="displayedSeries[1]" :live-readings="phReadings" :window="window" :now="now" :paused="!!paused" :show-average="showAverage" title="pH" value-key="value" unit="" color="#7546b6" />
      <TemperatureHistory :readings="displayedSeries[2]" :live-readings="odReadings" :window="window" :now="now" :paused="!!paused" :show-average="showAverage" title="Densidade óptica (OD)" value-key="value" unit="" color="#087d78" />
    </div>
  </template>
</template>
