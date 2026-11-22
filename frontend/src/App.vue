<script setup>
import { nextTick, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { request } from './api'
import { parseOdLimits } from './odLimits.js'

const router = useRouter()
const experiments = ref([])
const vials = ref([])
const loading = ref(true)
const loadError = ref('')
const dialog = ref(null)
const name = ref('')
const cultureType = ref('')
const cultureTypeError = ref('')
const vialId = ref('')
const odLimits = reactive({ od_min: '', od_max: '' })
const odErrors = ref({})
const odFields = { od_min: 'OD mínima', od_max: 'OD máxima' }
const saving = ref(false)
const formError = ref('')
const notice = ref('')
const noVials = 'Todos os vials estão em uso. Inative ou exclua um experimento para liberar um vial.'

async function refresh() {
  loading.value = true
  loadError.value = ''
  try {
    const [nextExperiments, nextVials] = await Promise.all([
      request('/experiments'),
      request('/vials/available'),
    ])
    experiments.value = nextExperiments
    vials.value = nextVials
    if (!nextVials.some((vial) => vial.vial_id === vialId.value)) vialId.value = ''
  } catch (error) {
    loadError.value = error.message
  } finally {
    loading.value = false
  }
}

function openForm() {
  name.value = ''
  cultureType.value = ''
  cultureTypeError.value = ''
  vialId.value = ''
  Object.assign(odLimits, { od_min: '', od_max: '' })
  odErrors.value = {}
  formError.value = ''
  dialog.value.showModal()
}

function validateCultureType(event) {
  cultureTypeError.value = 'Informe o tipo de cultura.'
  event.target.focus()
}

function updateOdErrors() {
  if (odErrors.value.od_min || odErrors.value.od_max) {
    odErrors.value = parseOdLimits(odLimits).errors
  }
}

async function createExperiment() {
  if (saving.value) return
  formError.value = ''
  const { errors, values } = parseOdLimits(odLimits)
  odErrors.value = errors
  const firstInvalid = Object.keys(odFields).find((field) => errors[field])
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
      body: JSON.stringify({
        name: name.value.trim(),
        culture_type: cultureType.value.trim(),
        vial_id: vialId.value,
        ...values,
      }),
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

onMounted(refresh)
</script>

<template>
  <div class="workspace">
    <aside class="sidebar">
      <RouterLink class="brand" to="/">eVOLVER <span>CNPEM</span></RouterLink>
      <div class="sidebar-header">
        <h2 id="menu-title">Experimentos</h2>
        <button class="primary" :disabled="loading || !!loadError || !vials.length" @click="openForm">
          Criar experimento
        </button>
      </div>
      <p v-if="loading" class="muted" role="status">Carregando experimentos…</p>
      <div v-else-if="loadError" class="message" role="alert">
        <p>{{ loadError }}</p>
        <button @click="refresh">Tentar novamente</button>
      </div>
      <p v-else-if="!vials.length" class="message" role="status">
        {{ noVials }}
      </p>
      <nav aria-labelledby="menu-title">
        <ul class="experiments">
          <li v-for="experiment in experiments" :key="experiment.id">
            <RouterLink :to="{ name: 'experiment', params: { id: experiment.id } }">
              <strong>{{ experiment.name }}</strong>
              <span>Vial {{ experiment.vial_id }} · {{ experiment.status === 'active' ? 'Ativo' : 'Inativo' }}</span>
            </RouterLink>
          </li>
        </ul>
        <p v-if="!loading && !loadError && !experiments.length" class="muted">Nenhum experimento cadastrado.</p>
      </nav>
    </aside>

    <main>
      <p class="notice" role="status" v-if="notice">{{ notice }}</p>
      <RouterView v-slot="{ Component, route }">
        <component :is="Component" :key="route.path" @changed="changed" />
      </RouterView>
    </main>
  </div>

  <dialog ref="dialog" aria-labelledby="create-title" @cancel="saving && $event.preventDefault()">
    <form @submit.prevent="createExperiment">
      <h2 id="create-title">Novo experimento</h2>
      <label for="name">Nome</label>
      <input id="name" v-model="name" type="text" maxlength="120" required autofocus />
      <label for="culture-type">Tipo de cultura</label>
      <input
        id="culture-type"
        v-model="cultureType"
        type="text"
        required
        pattern=".*[^\s\u0085].*"
        :aria-invalid="cultureTypeError ? 'true' : undefined"
        :aria-describedby="cultureTypeError ? 'culture-type-error' : undefined"
        @invalid.prevent="validateCultureType"
        @input="cultureTypeError = ''"
      />
      <p v-if="cultureTypeError" id="culture-type-error" class="error" role="alert">{{ cultureTypeError }}</p>
      <label for="vial">Vial</label>
      <select id="vial" v-model="vialId" required :disabled="loading || !vials.length">
        <option value="" disabled>Selecione um vial</option>
        <option v-for="vial in vials" :key="vial.vial_id" :value="vial.vial_id">
          {{ vial.label ?? `Vial ${vial.vial_id}` }}
        </option>
      </select>
      <p id="od-limits-hint" class="muted">Limites obrigatórios de 0,10 a 0,80. Use vírgula decimal.</p>
      <template v-for="(label, field) in odFields" :key="field">
        <label :for="field">{{ label }}</label>
        <input
          :id="field"
          v-model="odLimits[field]"
          :name="field"
          type="text"
          inputmode="decimal"
          autocomplete="off"
          spellcheck="false"
          aria-required="true"
          :aria-invalid="odErrors[field] ? 'true' : undefined"
          :aria-describedby="odErrors[field] ? `od-limits-hint ${field}-error` : 'od-limits-hint'"
          @input="updateOdErrors"
        />
        <p v-if="odErrors[field]" :id="`${field}-error`" class="error" role="alert">
          {{ odErrors[field] }}
        </p>
      </template>
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
