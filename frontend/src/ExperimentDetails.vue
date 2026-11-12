<script setup>
import { nextTick, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { request } from './api'
import TemperatureHistory from './TemperatureHistory.vue'

const props = defineProps({ id: { type: String, default: '' } })
const emit = defineEmits(['changed'])
const router = useRouter()
const experiment = ref(null)
const readings = ref([])
const loading = ref(false)
const error = ref('')
const actionError = ref('')
const pending = ref(false)
const heading = ref(null)
const base = `/experiments/${encodeURIComponent(props.id)}`
const dateTime = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'short' })

async function load() {
  if (!props.id) return
  loading.value = true
  error.value = ''
  try {
    const [details, history] = await Promise.all([request(base), request(`${base}/temperature-readings`)])
    experiment.value = details
    readings.value = history
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
  if (!window.confirm(confirmation)) return
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

onMounted(load)
</script>

<template>
  <section v-if="!id" class="panel empty">
    <h1>Experimentos</h1>
    <p class="muted">Selecione um experimento no menu para ver suas leituras de temperatura.</p>
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
        <p class="muted">Início · {{ dateTime.format(new Date(experiment.started_at)) }}</p>
        <p v-if="experiment.ended_at" class="muted">Fim · {{ dateTime.format(new Date(experiment.ended_at)) }}</p>
      </div>
      <div class="actions">
        <button v-if="experiment.status === 'active'" :disabled="pending" @click="change('inactivate')">Inativar</button>
        <button class="danger" :disabled="pending" @click="change('delete')">Excluir</button>
      </div>
    </header>
    <p v-if="actionError" class="error" role="alert">{{ actionError }}</p>
    <TemperatureHistory :readings="readings" />
  </template>
</template>
