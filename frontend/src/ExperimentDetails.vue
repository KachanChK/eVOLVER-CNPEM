<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, shallowRef, watch } from 'vue'
import { RouterLink, useRouter } from 'vue-router'
import { request } from './api'
import TemperatureHistory from './TemperatureHistory.vue'
import { historyWindow, latestGeneratedAt, PERIODS, readingAge, readingPoints } from './history.js'
import { experimentCode } from './experimentCode.js'
import { commandAction, commandStatus, isFinal, isOld, odValue, pumpReason, pumpState, pumpTime } from './pumpHistory.js'
import { formatOdLimits } from './odLimits.js'
import liveDot from './assets/live-dot.svg'
import updateDot from './assets/update-dot.svg'
import pauseIcon from './assets/pause.svg'
import phDot from './assets/ph-dot.svg'
import temperatureDot from './assets/temperature-dot.svg'
import odDot from './assets/od-dot.svg'
import expandIcon from './assets/expand.svg'
import collapseIcon from './assets/collapse.svg'

const props = defineProps({ id: { type: String, default: '' } })
const emit = defineEmits(['changed'])
const router = useRouter()
const experiment = ref(null)
const readings = ref([])
const phReadings = ref([])
const fallbackOdReadings = ref([])
const loading = ref(false)
const initialReadings = ref(true)
const error = ref('')
const actionError = ref('')
const pending = ref(false)
const closure = ref(null)
const closureError = ref('')
const closing = computed(() => !experiment.value?.ended_at &&
  ['pending', 'unconfirmed'].includes(closure.value?.state))
const heading = ref(null)
const period = ref(60_000)
const showAverage = ref(false)
const paused = shallowRef(null)
const now = ref(Date.now())
const viewTime = ref(Date.now())
const updateError = ref('')
const pumpStatus = {
  automatic: 'Bombas em modo automático',
  pausing: 'Pausando…',
  paused: 'Bombas pausadas',
  off_unconfirmed: 'Desligamento não confirmado. O modo automático está pausado.',
  resuming: 'Despausando… Aguardando a confirmação do desligamento.',
  resume_off_unconfirmed: 'Desligamento não confirmado. Aguardando reconciliação.',
}
const pumpSnapshot = shallowRef(null)
const pump = computed(() => pumpSnapshot.value?.pump)
const pumpHistory = computed(() => pumpSnapshot.value?.history)
const odReadings = computed(() => pumpSnapshot.value
  ? (pumpSnapshot.value.od_readings ?? []) : fallbackOdReadings.value)
const lastOd = computed(() => pumpSnapshot.value
  ? pumpSnapshot.value.latest_od
  : readingPoints(odReadings.value, 'value').at(-1)?.reading)
const lastChange = computed(() => pumpHistory.value?.transitions?.at(-1))
const pendingCommand = computed(() => pumpHistory.value?.commands?.find(command =>
  command.command_id === pump.value?.pending_command_id))
const lastResult = computed(() => pumpHistory.value?.commands?.reduce((latest, command) =>
  isFinal(command) && command.result_at && (!latest || Date.parse(command.result_at) >= Date.parse(latest.result_at))
    ? command : latest, null))
const displayedPumpHistory = computed(() => paused.value ? paused.value.pump : pumpHistory.value)
const pumpError = ref('')
const pendingPump = ref(false)
const pumpAction = computed(() => ['paused', 'pausing', 'off_unconfirmed'].includes(pump.value?.state)
  ? 'resume' : 'pause')
const liveSeries = computed(() => [phReadings.value, readings.value, odReadings.value])
const displayedSeries = computed(() => paused.value?.series ?? liveSeries.value)
const window = computed(() => historyWindow(
  displayedSeries.value,
  period.value,
  paused.value?.at ?? viewTime.value,
  paused.value ? paused.value.endedAt : experiment.value?.ended_at,
  experiment.value?.started_at,
))
const rangeDate = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'medium' })
const rangeLabel = computed(() => `${rangeDate.format(window.value.min)} — ${rangeDate.format(window.value.max)}`)
const clockTime = new Intl.DateTimeFormat('pt-BR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
const readingTime = new Intl.DateTimeFormat('pt-BR', {
  day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
  second: '2-digit', fractionalSecondDigits: 3,
})
const readingNumber = new Intl.NumberFormat('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const measurements = [
  { id: 'ph', title: 'pH', unit: 'pH', key: 'value', color: '#7546b6', icon: phDot, number: readingNumber },
  { id: 'temperature', title: 'Temperatura', unit: '°C', key: 'temperature_celsius', color: '#a34b24', icon: temperatureDot, number: readingNumber },
  { id: 'od', title: 'Densidade óptica', unit: 'OD', key: 'value', color: '#087d91', icon: odDot, number: odValue },
]
const measurementPoints = computed(() => measurements.map((measure, index) => ({
  ...measure,
  points: readingPoints(displayedSeries.value[index], measure.key),
})))
const latestGenerated = computed(() => liveSeries.value.map(latestGeneratedAt))
const currentReadings = computed(() => measurementPoints.value.map((measure, index) => ({
  ...measure,
  latest: measure.points.at(-1),
  freshness: readingAge(latestGenerated.value[index], now.value),
  stale: Number.isFinite(latestGenerated.value[index]) && now.value - latestGenerated.value[index] > 15_000,
})))
const historyOpen = ref(false)
const historyMeasure = ref('')
const historyPage = ref(1)
const historyPageSize = 50
const historyRows = computed(() => {
  if (!historyOpen.value) return []
  const { min, max } = window.value
  const series = measurementPoints.value.filter(measure => !historyMeasure.value || measure.id === historyMeasure.value)
  return series.flatMap(measure => measure.points
    .filter(point => point.x >= min && point.x <= max)
    .map(({ x, y, reading }) => ({
      key: `${measure.id}-${reading.event_id}-${x}`,
      generated: x,
      received: Date.parse(reading.received_at),
      title: measure.title,
      value: y,
      number: measure.number,
      unit: measure.unit,
    }))).sort((a, b) => b.generated - a.generated || (b.received - a.received || 0))
})
const historyPages = computed(() => Math.max(1, Math.ceil(historyRows.value.length / historyPageSize)))
const historyPageRows = computed(() => {
  const offset = (historyPage.value - 1) * historyPageSize
  return historyRows.value.slice(offset, offset + historyPageSize)
})
watch([period, paused, historyOpen, historyMeasure], () => { historyPage.value = 1 })
watch(historyPages, count => { historyPage.value = Math.min(historyPage.value, count) })

function togglePause() {
  if (paused.value) {
    paused.value = null
    viewTime.value = Date.now()
  } else {
    paused.value = {
      series: liveSeries.value, pump: pumpHistory.value,
      at: viewTime.value, endedAt: experiment.value?.ended_at,
    }
  }
}
const base = `/experiments/${encodeURIComponent(props.id)}`
const dateTime = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' })
let pollTimer
let clockTimer
let detailsRequest = false
let readingRequest = false
let closureRequest = false
let pumpRequest = null
let disposed = false
let actionRevision = 0
let pumpRevision = 0

async function loadReadings() {
  if (readingRequest || pending.value) return
  readingRequest = true
  try {
    const options = { signal: AbortSignal.timeout(5000) }
    const [temperature, ph, od] = await Promise.all([
      request(`${base}/temperature-readings`, options),
      request(`${base}/readings/ph`, options),
      pumpSnapshot.value ? undefined : request(`${base}/readings/od`, options),
    ])
    if (disposed) return
    readings.value = temperature
    phReadings.value = ph
    if (od) fallbackOdReadings.value = od
    updateError.value = ''
  } catch {
    if (!disposed) {
      updateError.value = 'Não foi possível atualizar as leituras. Exibindo os últimos dados recebidos.'
    }
  } finally {
    readingRequest = false
    initialReadings.value = false
    viewTime.value = Date.now()
  }
}

function invalidatePump() {
  pumpRevision++
  pumpRequest?.abort()
  pumpRequest = null
}

async function loadPump(afterAction = false) {
  if (disposed || pumpRequest || (pendingPump.value && !afterAction) || pending.value) return
  const controller = new AbortController()
  pumpRequest = controller
  try {
    const signal = AbortSignal.any([controller.signal, AbortSignal.timeout(5000)])
    const snapshot = await request(`${base}/pump/snapshot`, { signal })
    if (disposed || pumpRequest !== controller) return
    pumpSnapshot.value = snapshot
    viewTime.value = Date.now()
    pumpError.value = ''
  } catch {
    if (!disposed && pumpRequest === controller) {
      pumpError.value = 'Não foi possível atualizar o estado das bombas. A atualização será tentada novamente.'
    }
  } finally {
    if (pumpRequest === controller) pumpRequest = null
  }
}

async function loadDetails() {
  if (detailsRequest || pending.value) return
  detailsRequest = true
  const initial = !experiment.value
  const revision = actionRevision
  if (initial) {
    loading.value = true
    error.value = ''
  }
  try {
    const data = await request(base, { signal: AbortSignal.timeout(5000) })
    if (disposed || revision !== actionRevision) return
    const endedAt = data.ended_at ?? experiment.value?.ended_at ?? closure.value?.ended_at
    experiment.value = endedAt ? { ...data, status: 'inactive', ended_at: endedAt } : data
  } catch (failure) {
    if (initial && !disposed && revision === actionRevision) error.value = failure.message
  } finally {
    detailsRequest = false
    if (initial) loading.value = false
  }
  if (initial && experiment.value) {
    await nextTick()
    heading.value?.focus({ preventScroll: true })
  }
}

async function applyClosure(next, announce = false) {
  if (experiment.value?.ended_at && next.state !== 'completed') return
  const previous = closure.value
  closure.value = next
  if (next.state === 'none') return
  if (previous?.state !== next.state || previous?.action !== next.action) {
    invalidatePump()
    if (next.state !== 'completed' || next.action !== 'delete') loadPump()
  }
  actionError.value = ''
  if (next.state !== 'completed' ||
      (previous?.state === 'completed' && previous.action === next.action && !announce)) return

  if (next.action === 'delete') {
    emit('changed', 'Experimento excluído da interface.')
    await router.replace({ name: 'home' })
  } else {
    if (experiment.value) {
      experiment.value = { ...experiment.value, status: 'inactive', ended_at: next.ended_at }
    }
    if (announce || previous?.action) emit('changed', 'Experimento inativado. Vial liberado.')
  }
}

async function loadClosure() {
  if (closureRequest || pending.value) return
  closureRequest = true
  const revision = actionRevision
  try {
    const state = await request(`${base}/closure`, { signal: AbortSignal.timeout(5000) })
    if (disposed || revision !== actionRevision) return
    closureError.value = ''
    await applyClosure(state)
  } catch (failure) {
    if (!disposed && revision === actionRevision && failure.status !== 404) {
      closureError.value = 'Não foi possível consultar o encerramento. A consulta será repetida.'
    }
  } finally {
    closureRequest = false
  }
}

async function change(action) {
  const retrying = closing.value && closure.value.state === 'unconfirmed' &&
    closure.value.action === action
  if (pending.value || (!retrying && (pendingPump.value || closing.value))) return
  const deleting = action === 'delete'
  const confirmation = deleting
    ? 'Excluir este experimento da interface? O histórico será preservado no banco.'
    : 'Inativar este experimento e liberar o vial? O histórico continuará disponível.'
  if (!retrying && !globalThis.confirm(confirmation)) return
  actionRevision++
  invalidatePump()
  pending.value = true
  actionError.value = ''
  closureError.value = ''
  try {
    const result = await request(deleting ? base : `${base}/inactivate`, {
      method: deleting ? 'DELETE' : 'POST',
      signal: AbortSignal.timeout(10000),
    })
    if (disposed) return
    if (result?.state === 'pending') {
      await applyClosure(result)
      emit('changed', '')
    } else if (deleting ? result === undefined : result?.status === 'inactive' && result.ended_at) {
      if (!deleting) experiment.value = result
      await applyClosure({ state: 'completed', action, ended_at: result?.ended_at }, true)
    } else {
      actionError.value = 'A API não confirmou o encerramento. Aguarde a atualização ou tente novamente.'
    }
  } catch (failure) {
    if (!disposed) actionError.value = failure.message
  } finally {
    pending.value = false
    if (!deleting || closure.value?.state !== 'completed') loadPump()
  }
}

async function changePumpMode() {
  if (pending.value || pendingPump.value || closing.value ||
      experiment.value?.ended_at || pump.value?.ending) return
  invalidatePump()
  const revision = pumpRevision
  const signal = AbortSignal.timeout(10000)
  pendingPump.value = true
  pumpError.value = ''
  try {
    await request(`${base}/pump/${pumpAction.value}`, { method: 'POST', signal })
    if (!disposed && revision === pumpRevision && !experiment.value?.ended_at) {
      await loadPump(true)
    }
  } catch (failure) {
    if (!disposed && revision === pumpRevision && !experiment.value?.ended_at) {
      pumpError.value = signal.aborted
        ? 'A API demorou para responder. O estado das bombas será consultado novamente.'
        : failure.message
    }
  } finally {
    pendingPump.value = false
  }
}

onMounted(() => {
  if (props.id) {
    const refresh = () => {
      loadDetails()
      loadClosure()
      loadPump()
      loadReadings()
    }
    refresh()
    pollTimer = setInterval(refresh, 5000)
  }
  clockTimer = setInterval(() => { now.value = Date.now() }, 1000)
})
onUnmounted(() => {
  disposed = true
  invalidatePump()
  clearInterval(pollTimer)
  clearInterval(clockTimer)
})
</script>

<template>
  <section v-if="!id" class="panel empty">
    <h1>Experimentos</h1>
    <p class="muted">Selecione um dos seus experimentos para ver suas leituras.</p>
  </section>
  <p v-else-if="loading" role="status">Carregando experimento…</p>
  <div v-else-if="error" class="panel" role="alert">
    <p>{{ error }}</p>
    <button type="button" @click="loadDetails">Tentar novamente</button>
  </div>
  <div v-else-if="experiment" class="experiment-dashboard">
    <header class="detail-header">
      <nav class="breadcrumb" aria-label="Localização atual">
        <RouterLink to="/">Experimentos</RouterLink>
        <span aria-hidden="true">/</span>
        <span aria-current="page" translate="no">{{ experimentCode(experiment.id) }}</span>
      </nav>
      <h1 ref="heading" tabindex="-1">{{ experiment.name }}</h1>
      <div class="detail-meta">
        <ul>
          <li class="vial">Vial {{ experiment.vial_id }} · {{ experiment.status === 'active' ? 'Ativo' : 'Inativo' }}</li>
          <li>Tipo de cultura · {{ experiment.culture_type ?? 'Não informado' }}</li>
          <li>Limites de OD · {{ formatOdLimits(experiment) }}</li>
          <li>Início · <time :datetime="experiment.started_at">{{ dateTime.format(new Date(experiment.started_at)) }}</time></li>
          <li v-if="experiment.ended_at">Fim · <time :datetime="experiment.ended_at">{{ dateTime.format(new Date(experiment.ended_at)) }}</time></li>
        </ul>
        <div v-if="!closing" class="actions detail-actions">
          <p v-if="experiment.status === 'active' && !paused && !initialReadings && !updateError && currentReadings.some(measure => measure.latest && !measure.stale)" class="live-status">
            <img :src="liveDot" alt="" width="8" height="8" /> Ao vivo
          </p>
          <button v-if="experiment.status === 'active'" type="button" :disabled="pending || pendingPump" @click="change('inactivate')">Inativar</button>
          <button type="button" class="danger" :disabled="pending || pendingPump" @click="change('delete')">Excluir</button>
        </div>
      </div>
    </header>
    <p v-if="actionError" class="error" role="alert">{{ actionError }}</p>
    <p v-if="closureError" class="error" role="alert">{{ closureError }}</p>
    <section v-if="closing" class="notice" aria-label="Encerramento do experimento">
      <p role="status">
        {{ closure.action === 'delete' ? 'Exclusão' : 'Inativação' }} solicitada.
        {{ closure.state === 'pending'
          ? 'Aguardando a confirmação de que as bombas desligaram. O vial continua ocupado.'
          : 'O desligamento das bombas ficou sem confirmação. O vial continua ocupado. Verifique se o simulador está conectado e tente novamente.' }}
      </p>
      <button v-if="closure.state === 'unconfirmed'" type="button" :disabled="pending"
        @click="change(closure.action)">Tentar desligar novamente</button>
    </section>
    <section aria-labelledby="current-readings">
      <h2 id="current-readings">{{ paused ? 'Leituras exibidas' : experiment.status === 'active' ? 'Leituras em tempo real' : 'Últimas leituras' }}</h2>
      <div class="reading-cards">
        <div v-for="measure in currentReadings" :key="measure.id" class="panel reading-card">
          <h3>{{ measure.title }}</h3>
          <p class="reading-value">
            <strong>{{ measure.latest ? measure.number.format(measure.latest.y) : '—' }}</strong>
            <span v-if="measure.latest">{{ measure.unit }}</span>
          </p>
          <p v-if="measure.latest" class="muted">
            Última leitura às <time :datetime="measure.latest.reading.generated_at">{{ clockTime.format(measure.latest.x) }}</time>
          </p>
          <p v-else class="muted">{{ initialReadings ? 'Carregando…' : 'Sem leituras' }}</p>
          <p v-if="measure.stale && experiment.status === 'active'" class="freshness stale">{{ measure.freshness }}</p>
        </div>
      </div>
    </section>

    <section class="measurement-history" aria-labelledby="history-heading">
      <div class="history-toolbar">
        <div>
          <h2 id="history-heading">Histórico das medidas</h2>
          <p class="muted history-range">{{ rangeLabel }}</p>
        </div>
        <div class="period-control">
          <span id="period-label">Período</span>
          <div class="period-buttons" role="group" aria-labelledby="period-label">
            <button v-for="choice in PERIODS" :key="choice.label" :aria-pressed="period === choice.value"
              type="button" @click="period = choice.value">{{ choice.label }}</button>
          </div>
        </div>
      </div>
      <div class="history-toolbar history-secondary">
        <p :class="['view-status', { paused }]" role="status">
          <img v-if="!paused && experiment.status === 'active'" :src="updateDot" alt="" width="7" height="7" />
          {{ paused ? 'Visualização pausada. A coleta de dados continua.' : experiment.status === 'active' ? 'Atualização a cada 5 s' : 'Histórico do experimento encerrado' }}
        </p>
        <div class="history-actions">
          <label class="average-toggle"><input v-model="showAverage" type="checkbox" name="show_average"> Mostrar média de 5 s</label>
          <button class="pause-button" type="button" :aria-pressed="!!paused" @click="togglePause">
            <img v-if="!paused" :src="pauseIcon" alt="" width="15" height="15" />
            {{ paused ? 'Retomar visualização' : 'Pausar visualização' }}
          </button>
        </div>
      </div>
      <p v-if="updateError" class="notice" role="alert">{{ updateError }}</p>
      <p v-if="initialReadings" role="status">Carregando leituras…</p>
      <div v-else class="history-panels">
        <TemperatureHistory v-for="measure in measurementPoints" :key="measure.id"
          :class="{ 'measurement-wide': measure.id === 'ph' }"
          :points="measure.points" :title="measure.title" :unit="measure.unit" :color="measure.color" :icon="measure.icon"
          :window="window" :show-average="showAverage"
          :od-limits="measure.id === 'od' ? experiment : null"
          :pump-history="measure.id === 'od' ? displayedPumpHistory : null" />
      </div>
    </section>

    <section class="pump-panel panel" aria-labelledby="pump-heading">
      <div class="pump-controls">
        <h2 id="pump-heading">Controle de OD</h2>
        <button v-if="pump && experiment.status === 'active' && !closing && !pump.ending"
          type="button" :disabled="pending || pendingPump" @click="changePumpMode">
          {{ pumpAction === 'pause' ? 'Pausar bombas' : 'Despausar bombas' }}
        </button>
      </div>
      <dl class="pump-summary">
        <div>
          <dt>Última OD</dt>
          <dd v-if="lastOd">
            <strong>{{ odValue.format(lastOd.value) }}</strong>
            <time :datetime="lastOd.generated_at">{{ pumpTime.format(new Date(lastOd.generated_at)) }}</time>
            <span v-if="isOld(lastOd.generated_at, now)" class="freshness stale">Leitura antiga</span>
          </dd>
          <dd v-else>Sem medições</dd>
        </div>
        <div>
          <dt>Modo de controle</dt>
          <dd role="status">
            {{ pumpSnapshot?.ended_at ? 'Encerrado' : pump?.ending ? 'Pausado para encerrar' :
              pump ? pumpStatus[pump.state] : 'Aguardando consulta' }}
          </dd>
        </div>
        <div>
          <dt>Estado das bombas</dt>
          <dd role="status">{{ pumpState[pump?.confirmed_state] ?? pumpState.unknown }}</dd>
        </div>
        <div>
          <dt>Comando pendente</dt>
          <dd v-if="pump?.pending_command_id">
            {{ pendingCommand ? commandAction(pendingCommand) + ' · ' + commandStatus[pendingCommand.result_status] : 'Aguardando atualização' }}
            <code translate="no">{{ pump.pending_command_id }}</code>
          </dd>
          <dd v-else>{{ pump ? 'Nenhum' : 'Aguardando consulta' }}</dd>
        </div>
        <div>
          <dt>Última mudança</dt>
          <dd v-if="lastChange">
            {{ pumpReason[lastChange.reason] ?? lastChange.reason }}
            <time :datetime="lastChange.observed_at">{{ pumpTime.format(new Date(lastChange.observed_at)) }}</time>
          </dd>
          <dd v-else>Sem mudanças registradas</dd>
        </div>
        <div>
          <dt>Último resultado registrado</dt>
          <dd v-if="lastResult" :data-command-id="lastResult.command_id">
            {{ commandAction(lastResult) }} · {{ commandStatus[lastResult.result_status] ?? lastResult.result_status }}
            <time :datetime="lastResult.result_at">{{ pumpTime.format(new Date(lastResult.result_at)) }}</time>
            <span v-if="isOld(lastResult.result_at, now)" class="freshness stale">Resultado antigo</span>
          </dd>
          <dd v-else>Sem resultado registrado</dd>
        </div>
      </dl>
      <p v-if="pumpError" class="error" role="alert">{{ pumpError }}</p>
    </section>

    <details class="panel readings-history" @toggle="historyOpen = $event.target.open">
      <summary class="readings-summary">
        <span>
          <strong>Histórico de medições</strong>
          <span class="muted">Leituras do período selecionado</span>
        </span>
        <span class="readings-disclosure">
          {{ historyOpen ? 'Ocultar leituras' : 'Mostrar leituras' }}
          <img :src="historyOpen ? collapseIcon : expandIcon" alt="" width="16" height="16" />
        </span>
      </summary>
      <template v-if="historyOpen">
        <label class="history-filter">
          Medida
          <select v-model="historyMeasure" name="measurement">
            <option value="">Todas as medidas</option>
            <option v-for="measure in measurements" :key="measure.id" :value="measure.id">{{ measure.title }}</option>
          </select>
        </label>
        <p v-if="initialReadings" class="history-empty muted" role="status">Carregando leituras…</p>
        <p v-else-if="!historyRows.length" class="history-empty muted">Sem leituras neste período.</p>
        <template v-else>
          <p class="table-scroll-hint muted">Role a tabela na horizontal para ver todas as colunas.</p>
          <div class="table-scroll" tabindex="0" role="region" aria-label="Leituras do período selecionado">
            <table>
              <thead>
                <tr><th scope="col">Gerada em</th><th scope="col">Recebida em</th><th scope="col">Medida</th><th scope="col">Valor</th></tr>
              </thead>
              <tbody>
                <tr v-for="row in historyPageRows" :key="row.key">
                  <td><time :datetime="new Date(row.generated).toISOString()">{{ readingTime.format(row.generated) }}</time></td>
                  <td v-if="Number.isFinite(row.received)"><time :datetime="new Date(row.received).toISOString()">{{ readingTime.format(row.received) }}</time></td>
                  <td v-else>—</td>
                  <td>{{ row.title }}</td>
                  <td>{{ row.number.format(row.value) }}&nbsp;{{ row.unit }}</td>
                </tr>
              </tbody>
            </table>
          </div>
          <nav v-if="historyPages > 1" class="table-pages" aria-label="Páginas do histórico de medições">
            <button type="button" :disabled="historyPage === 1" @click="historyPage--">Mais recentes</button>
            <span aria-live="polite">Página {{ historyPage }} de {{ historyPages }}</span>
            <button type="button" :disabled="historyPage === historyPages" @click="historyPage++">Mais antigas</button>
          </nav>
        </template>
      </template>
    </details>
  </div>
</template>
