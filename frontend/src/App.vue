<script setup>
import { nextTick, onMounted, onUnmounted, reactive, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { request } from './api'
import { createAlertFeed } from './alerts.js'
import { encodeExperiment, formatOdInput, MAX_OD_INPUT_DECIMALS, parseOdLimits } from './odLimits.js'
import { experimentCode } from './experimentCode.js'
import VialPicker from './VialPicker.vue'
import AlertDetails from './AlertDetails.vue'
import experimentsIcon from './assets/flask.svg'
import simulatorIcon from './assets/cube.svg'
import plusIcon from './assets/plus.svg'

const router = useRouter()
const alertFeed = createAlertFeed(request, () => router.currentRoute.value.name === 'alerts')
const experiments = ref([])
const allocationSource = ref('demo')
const vials = ref([])
const loading = ref(true)
const loadError = ref('')
const dialog = ref(null)
const name = ref('')
const cultureType = ref('')
const cultureTypeError = ref('')
const vialId = ref('')
const vialNotice = ref('')
const odLimits = reactive({ od_min: '', od_max: '' })
const odErrors = ref({})
const odFields = { od_min: 'OD mínima', od_max: 'OD máxima' }
const saving = ref(false)
const formError = ref('')
const notice = ref('')
const noVials = 'Todos os vials estão em uso. Inative ou exclua um experimento para liberar um vial.'
const nameMaxLength = 40
const cultureTypeMaxLength = 30

let refreshRevision = 0
let backgroundRequest = false
let refreshTimer

async function refresh(background = false) {
  if (background && (loading.value || backgroundRequest)) return
  if (background) backgroundRequest = true
  const revision = ++refreshRevision
  if (!background) {
    loading.value = true
    loadError.value = ''
  }
  try {
    const options = { signal: AbortSignal.timeout(10000) }
    const [nextExperiments, nextVials] = await Promise.all([
      request('/experiments', options),
      request('/vials/available', options),
    ])
    if (revision !== refreshRevision) return
    loadError.value = ''
    experiments.value = nextExperiments
    allocationSource.value = 'live'
    vials.value = nextVials
    if (vialId.value && !nextVials.some((vial) => vial.vial_id === vialId.value)) {
      vialId.value = ''
      if (nextVials.length) vialNotice.value = 'O vial selecionado ficou indisponível. Escolha outro.'
    }
  } catch (error) {
    if (revision !== refreshRevision) return
    if (allocationSource.value === 'live') allocationSource.value = 'stale'
    if (!background) loadError.value = error.message
  } finally {
    if (background) backgroundRequest = false
    if (revision === refreshRevision) loading.value = false
  }
}

function openForm() {
  name.value = ''
  cultureType.value = ''
  cultureTypeError.value = ''
  vialId.value = ''
  vialNotice.value = ''
  Object.assign(odLimits, { od_min: '', od_max: '' })
  odErrors.value = {}
  formError.value = ''
  dialog.value.showModal()
}

function validateCultureType(event) {
  cultureTypeError.value = 'Informe o tipo de cultura.'
  event.target.focus()
}

function updateOdLimit(field, event) {
  if (event.isComposing) return
  const input = event.target
  const { value, selectionStart } = input
  const formatted = formatOdInput(value, event.inputType?.startsWith('delete')) ?? odLimits[field]
  if (formatted !== value) {
    const caret = event.inputType === 'deleteContentBackward' && selectionStart <= 1
      ? selectionStart
      : selectionStart + formatted.length - value.length
    input.value = formatted
    input.setSelectionRange(Math.max(0, caret), Math.max(0, caret))
  }
  odLimits[field] = formatted
  if (odErrors.value.od_min || odErrors.value.od_max) {
    odErrors.value = parseOdLimits(odLimits).errors
  }
}

async function createExperiment() {
  if (saving.value || loading.value || loadError.value || !vialId.value) return
  formError.value = ''
  const limits = parseOdLimits(odLimits)
  odErrors.value = limits.errors
  const firstInvalid = Object.keys(odFields).find((field) => limits.errors[field])
  if (firstInvalid) {
    await nextTick()
    dialog.value.querySelector(`[name="${firstInvalid}"]`).focus()
    return
  }

  saving.value = true
  try {
    const experiment = await request('/experiments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: encodeExperiment({
        name: name.value.trim(),
        culture_type: cultureType.value.trim(),
        vial_id: vialId.value,
      }, limits),
    })
    dialog.value.close()
    await router.push({ name: 'experiment', params: { id: experiment.id } })
    await changed('Experimento criado.')
  } catch (error) {
    formError.value = error.message
    if (error.status === 409) await refresh()
  } finally {
    saving.value = false
  }
}

async function changed(message) {
  notice.value = message
  await refresh()
}

onMounted(() => {
  refresh()
  alertFeed.start()
  refreshTimer = setInterval(() => refresh(true), 5000)
})
onUnmounted(() => {
  alertFeed.stop()
  clearInterval(refreshTimer)
})
watch(() => router.currentRoute.value.name, (route) => {
  if (route === 'alerts') void alertFeed.poll()
})
</script>

<template>
  <a class="skip-link" href="#conteudo">Ir para o conteúdo</a>
  <div class="workspace">
    <aside class="sidebar">
      <RouterLink class="brand" to="/" translate="no">
        <strong>eVOLVER</strong> <span class="muted">CNPEM</span>
      </RouterLink>
      <nav class="system-nav" aria-labelledby="system-nav-title">
        <p id="system-nav-title">Páginas do sistema</p>
        <RouterLink class="system-link" :class="{ 'system-link-active': $route.name === 'experiment' }" to="/">
          <img :src="experimentsIcon" alt="" width="20" height="20" />
          Experimentos
        </RouterLink>
        <RouterLink class="system-link alerts-link" :to="{ name: 'alerts' }">
          <span class="alerts-link-icon" aria-hidden="true">!</span>
          Alertas
          <span v-if="alertFeed.state.hasUnread" class="alerts-unread">
            <span class="alerts-sr-only">com alertas não lidos</span>
          </span>
        </RouterLink>
        <RouterLink class="system-link" :to="{ name: 'simulator-preview' }">
          <img :src="simulatorIcon" alt="" width="20" height="20" />
          Prévia 3D
        </RouterLink>
      </nav>
      <nav class="experiment-nav" aria-labelledby="menu-title">
        <div class="sidebar-header">
          <p id="menu-title">Seus experimentos</p>
          <span v-if="!loadError && (!loading || experiments.length)" class="muted">{{ experiments.length }} no total</span>
        </div>
        <p v-if="loading && !experiments.length" class="muted" role="status">Carregando experimentos…</p>
        <div v-else-if="loadError" class="message" role="alert">
          <p>{{ loadError }}</p>
          <button type="button" @click="refresh()">Tentar novamente</button>
        </div>
        <ul class="experiments">
          <li v-for="experiment in experiments" :key="experiment.id">
            <RouterLink :to="{ name: 'experiment', params: { id: experiment.id } }">
              <span class="experiment-label">
                <span translate="no">{{ experimentCode(experiment.id) }}</span>
                <span>{{ experiment.status === 'active' ? 'Ativo' : 'Inativo' }}</span>
              </span>
              <strong class="experiment-name" :title="experiment.name">{{ experiment.name }}</strong>
            </RouterLink>
          </li>
        </ul>
        <p v-if="!loading && !loadError && !experiments.length" class="muted">Nenhum experimento cadastrado.</p>
      </nav>
      <div class="sidebar-actions">
        <p v-if="!loading && !loadError && !vials.length" class="message" role="status">{{ noVials }}</p>
        <button class="primary new-experiment" type="button" :disabled="loading || !!loadError" @click="openForm">
          <img :src="plusIcon" alt="" width="18" height="18" />
          Novo experimento
        </button>
      </div>
    </aside>

    <main id="conteudo" tabindex="-1">
      <p class="notice" role="status" v-if="notice">{{ notice }}</p>
      <RouterView v-slot="{ Component, route }">
        <component
          :is="Component"
          :key="route.path"
          v-bind="route.name === 'simulator-preview' ? { experiments, allocationSource }
            : route.name === 'alerts' ? { feed: alertFeed } : {}"
          @changed="changed"
        />
      </RouterView>
    </main>
  </div>

  <aside class="alert-notices" aria-label="Alertas recentes" aria-live="polite" aria-relevant="additions text">
    <article v-for="alert in alertFeed.state.notices" :id="'alert-notice-' + alert.id"
             :key="alert.id" class="panel alert-notice">
      <AlertDetails :alert="alert" />
      <button type="button" :aria-label="'Fechar alerta de ' + alert.experiment_name + ', vial ' + alert.vial_id"
              @click="alertFeed.dismiss(alert.id)">
        <span aria-hidden="true">×</span>
      </button>
    </article>
  </aside>

  <dialog ref="dialog" aria-labelledby="create-title" @cancel="saving && $event.preventDefault()">
    <form autocomplete="off" @submit.prevent="createExperiment">
      <h2 id="create-title">Novo experimento</h2>
      <div class="field-label">
        <label for="name">Nome</label>
        <span id="name-count" class="field-count muted">{{ name.length }}/{{ nameMaxLength }}</span>
      </div>
      <input id="name" v-model="name" name="name" type="text" :maxlength="nameMaxLength" aria-describedby="name-count" required />
      <div class="field-label">
        <label for="culture-type">Tipo de cultura</label>
        <span id="culture-type-count" class="field-count muted">{{ cultureType.length }}/{{ cultureTypeMaxLength }}</span>
      </div>
      <input
        id="culture-type"
        v-model="cultureType"
        name="culture_type"
        type="text"
        :maxlength="cultureTypeMaxLength"
        required
        pattern=".*[^\s\u0085].*"
        :aria-invalid="cultureTypeError ? 'true' : undefined"
        :aria-describedby="cultureTypeError ? 'culture-type-count culture-type-error' : 'culture-type-count'"
        @invalid.prevent="validateCultureType"
        @input="cultureTypeError = ''"
      />
      <p v-if="cultureTypeError" id="culture-type-error" class="error" role="alert">{{ cultureTypeError }}</p>
      <VialPicker
        v-model="vialId"
        :available="vials"
        :disabled="loading || saving || !!loadError"
        @update:model-value="vialNotice = ''"
      />
      <p v-if="vialNotice" class="message" role="status">{{ vialNotice }}</p>
      <p v-if="allocationSource === 'stale'" class="message" role="status">A disponibilidade dos vials está desatualizada.</p>
      <template v-for="(label, field) in odFields" :key="field">
        <div class="field-label">
          <label :for="field">{{ label }}</label>
          <span :id="`${field}-count`" class="field-count muted">
            {{ odLimits[field].split(',')[1]?.length ?? 0 }}/{{ MAX_OD_INPUT_DECIMALS }} decimais
          </span>
        </div>
        <input
          :id="field"
          :value="odLimits[field]"
          :name="field"
          type="text"
          inputmode="numeric"
          autocomplete="off"
          spellcheck="false"
          aria-required="true"
          :aria-invalid="odErrors[field] ? 'true' : undefined"
          :aria-describedby="`${field}-count od-limits-hint${odErrors[field] ? ` ${field}-error` : ''}`"
          @input="updateOdLimit(field, $event)"
          @compositionend="updateOdLimit(field, $event)"
        />
        <p v-if="odErrors[field]" :id="`${field}-error`" class="error" role="alert">
          {{ odErrors[field] }}
        </p>
      </template>
      <p id="od-limits-hint" class="muted">Limites obrigatórios de 0,10 a 0,80.</p>
      <p v-if="formError" class="error" role="alert">{{ formError }}</p>
      <p v-if="!loading && !loadError && !vials.length" class="message" role="status">{{ noVials }}</p>
      <div class="actions">
        <button type="button" :disabled="saving" @click="dialog.close()">Cancelar</button>
        <button class="primary" :disabled="saving || loading || !!loadError || !name.trim() || !vialId">
          {{ saving ? 'Criando…' : 'Criar experimento' }}
        </button>
      </div>
    </form>
  </dialog>
</template>
