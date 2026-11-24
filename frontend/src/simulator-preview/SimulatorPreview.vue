<script setup>
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { experimentCode } from '../experimentCode.js'
import { mountViewer, vialStates } from './preview.js'

const props = defineProps({
  experiments: { type: Array, required: true },
  allocationSource: { type: String, required: true },
})

const preview = ref(null)
const allocationLabels = {
  demo: 'Estados de exemplo',
  live: 'Alocações do painel',
  stale: 'Alocações desatualizadas',
}
const demoAllocations = new Map([[2, 101], [5, 102], [7, 103], [10, 104]])
const vialNumbers = Array.from({ length: 12 }, (_, index) => index + 1)
const vials = computed(() => {
  const active = props.allocationSource === 'demo'
    ? demoAllocations
    : new Map(props.experiments.filter(({ ended_at }) => ended_at === null).map(({ vial_id, id }) => [vial_id, id]))
  return vialNumbers.map(number => {
    const experimentId = active.get(number) ?? null
    return { number, experimentId, state: experimentId === null ? 'free' : 'used' }
  })
})

let viewer

onMounted(() => {
  viewer = mountViewer(preview.value, vials.value)
})
watch(vials, nextVials => viewer?.updateVials(nextVials))
onUnmounted(() => viewer?.dispose())
</script>

<template>
  <div ref="preview" class="simulator-preview">
    <h1>Prévia 3D</h1>

    <figure class="viewer">
      <canvas id="equipment" tabindex="0" aria-label="Maquete tridimensional do eVOLVER com 12 vials"
        aria-describedby="rotation-help" hidden></canvas>
      <p id="viewer-message" class="viewer-message" role="status">Carregando a maquete…</p>
      <div id="vial-card" class="vial-card" hidden>
        <strong id="vial-card-number"></strong>
        <span id="vial-card-state"></span>
        <span id="vial-card-experiment" class="vial-card-experiment" translate="no" hidden></span>
      </div>
      <figcaption id="rotation-help" hidden>Arraste para girar ou use as setas do teclado</figcaption>
    </figure>

    <section class="vials" aria-labelledby="vial-heading">
      <div class="vial-heading">
        <h2 id="vial-heading">Vials</h2>
        <p role="status">{{ allocationLabels[allocationSource] }}</p>
      </div>
      <ul class="vial-list" aria-label="Estado de cada vial" role="list">
        <li v-for="{ number, experimentId, state } in vials" :key="number" :data-state="state">
          <span class="state-mark" aria-hidden="true"></span>
          {{ String(number).padStart(2, '0') }}
          <span class="sr-only">, {{ vialStates[state].label }}<template v-if="experimentId !== null">, {{ experimentCode(experimentId) }}</template></span>
        </li>
      </ul>
      <ul class="legend" aria-label="Legenda" role="list">
        <li v-for="({ label }, state) in vialStates" :key="state" :data-state="state">
          <span class="state-mark" aria-hidden="true"></span>
          {{ label }}
        </li>
      </ul>
    </section>
  </div>
</template>

<style scoped src="./preview.css"></style>
