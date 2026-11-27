<script setup>
import { nextTick, ref } from 'vue'
import AlertDetails from './AlertDetails.vue'

const props = defineProps({ feed: { type: Object, required: true } })
const state = props.feed.state
const confirmation = ref(null)
const title = ref(null)
const clearError = ref('')
const pageError = ref('')

async function confirmClear() {
  clearError.value = ''
  try {
    await props.feed.clear()
    confirmation.value?.close()
    if (!state.items.length) title.value?.focus()
  } catch {
    clearError.value = 'Não foi possível limpar o histórico. Confirme novamente para tentar de novo.'
  }
}

async function loadOlder() {
  pageError.value = ''
  const previous = state.nextBefore
  try {
    await props.feed.loadOlder()
    await nextTick()
    const next = state.items.find((alert) => alert.id < previous)
    if (next) document.getElementById('alert-' + next.id)?.focus()
  } catch {
    pageError.value = 'Não foi possível buscar os alertas anteriores. Tente novamente.'
  }
}
</script>

<template>
  <section class="alerts-page" aria-labelledby="alerts-title">
    <header class="alerts-header">
      <h1 id="alerts-title" ref="title" tabindex="-1">Alertas</h1>
      <button v-if="state.items.length" class="danger" type="button" @click="clearError = ''; confirmation.showModal()">
        Limpar alertas
      </button>
    </header>

    <p v-if="state.error" class="message" role="status">{{ state.error }}</p>
    <p v-else-if="!state.ready" class="muted" role="status">Carregando alertas…</p>
    <p v-else-if="!state.items.length" class="panel muted" role="status">Nenhum alerta no histórico.</p>

    <ul v-if="state.items.length" class="alerts-list panel" aria-label="Histórico de alertas">
      <li v-for="alert in state.items" :id="'alert-' + alert.id" :key="alert.id" tabindex="-1">
        <AlertDetails :alert="alert" />
      </li>
    </ul>
    <p v-if="pageError" class="error" role="alert">{{ pageError }}</p>
    <button v-if="state.nextBefore" class="alerts-more" type="button"
            :disabled="state.loadingOlder" @click="loadOlder">
      {{ state.loadingOlder ? 'Carregando…' : 'Mostrar alertas anteriores' }}
    </button>

    <dialog ref="confirmation" aria-labelledby="clear-alerts-title" aria-describedby="clear-alerts-detail"
            @cancel="state.clearing && $event.preventDefault()">
      <form @submit.prevent="confirmClear">
        <h2 id="clear-alerts-title">Limpar alertas?</h2>
        <p id="clear-alerts-detail">Os alertas atuais serão arquivados. Alertas novos continuarão aparecendo aqui.</p>
        <p v-if="clearError" class="error" role="alert">{{ clearError }}</p>
        <div class="actions">
          <button type="button" :disabled="state.clearing" @click="confirmation.close()">Cancelar</button>
          <button class="primary" :disabled="state.clearing || !state.items.length">
            {{ state.clearing ? 'Limpando…' : 'Limpar alertas' }}
          </button>
        </div>
      </form>
    </dialog>
  </section>
</template>
