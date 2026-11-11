<script setup>
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { request } from './api'

const router = useRouter()
const experiments = ref([])
const vials = ref([])
const loading = ref(true)
const loadError = ref('')
const dialog = ref(null)
const name = ref('')
const vialId = ref('')
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
  vialId.value = ''
  formError.value = ''
  dialog.value.showModal()
}

async function createExperiment() {
  if (saving.value) return
  saving.value = true
  formError.value = ''
  try {
    const experiment = await request('/experiments', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name: name.value.trim(), vial_id: vialId.value }),
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
      <label for="vial">Vial</label>
      <select id="vial" v-model="vialId" required :disabled="loading || !vials.length">
        <option value="" disabled>Selecione um vial</option>
        <option v-for="vial in vials" :key="vial.vial_id" :value="vial.vial_id">
          {{ vial.label ?? `Vial ${vial.vial_id}` }}
        </option>
      </select>
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
