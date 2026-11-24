<script setup>
import { computed } from 'vue'
import vialTop from './assets/vial-top.png'

const props = defineProps({
  available: { type: Array, required: true },
  disabled: Boolean,
})
const selected = defineModel({ required: true })

// Vista superior da Prévia 3D, com a fileira 01–04 junto à frente do equipamento.
const positions = [9, 10, 11, 12, 5, 6, 7, 8, 1, 2, 3, 4]
const slots = computed(() => {
  const available = new Map(props.available.map(({ vial_id, label }) => [vial_id, label]))
  return positions.map(number => ({
    number,
    displayNumber: String(number).padStart(2, '0'),
    label: available.get(number) ?? `Vial ${String(number).padStart(2, '0')}`,
    free: available.has(number),
  }))
})
</script>

<template>
  <fieldset class="vial-picker" :disabled="disabled">
    <legend>Vial <span>Vista superior</span></legend>
    <div class="vial-tray">
      <div class="vial-grid">
        <label v-for="{ number, displayNumber, label, free } in slots" :key="number" class="vial-option">
          <input
            v-model="selected"
            type="radio"
            name="vial_id"
            :value="number"
            :disabled="!free"
            :required="free"
            :aria-label="`${label}, ${free ? 'livre' : 'em uso'}`"
          />
          <span class="vial-slot" :class="{ 'vial-slot-occupied': !free }">
            <img :src="vialTop" alt="" width="36" height="36" />
            <span class="vial-number">{{ displayNumber }}</span>
            <span class="vial-status">{{ free ? 'Livre' : 'Em uso' }}</span>
            <span v-if="selected === number" class="vial-check" aria-hidden="true">✓</span>
          </span>
        </label>
      </div>
      <p class="vial-front">Frente do equipamento</p>
    </div>
  </fieldset>
</template>

<style scoped>
.vial-picker { min-inline-size: 0; padding: 0; margin: .35rem 0 0; border: 0; }
legend { padding: 0; margin-bottom: .375rem; font-weight: 600; }
legend span { margin-inline-start: .375rem; color: var(--muted); font-size: .75rem; font-weight: 400; }
.vial-tray { padding: .4375rem; background: #edf1f5; border: 1px solid var(--line); border-radius: .625rem; }
.vial-grid { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: .375rem; }
.vial-option { position: relative; margin: 0; touch-action: manipulation; }
.vial-option input { position: absolute; inline-size: 1px; block-size: 1px; min-height: 0; padding: 0; clip-path: inset(50%); }
.vial-slot {
  display: grid;
  justify-items: center;
  padding: .1875rem .125rem .25rem;
  border: 1px solid #aeb8c7;
  border-radius: .375rem;
  background: var(--surface);
}
.vial-slot img { inline-size: min(100%, 2.25rem); block-size: auto; aspect-ratio: 1; }
.vial-number { font-size: .875rem; line-height: 1.125rem; font-variant-numeric: tabular-nums; }
.vial-status { color: #176443; font-size: .6875rem; font-weight: 500; line-height: 1rem; }
.vial-slot-occupied { background: #e2e7ed; border-color: #c6d0db; color: var(--muted); }
.vial-slot-occupied img { filter: grayscale(1); opacity: .64; }
.vial-slot-occupied .vial-status { color: var(--muted); }
.vial-option input:enabled + .vial-slot { cursor: pointer; }
@media (hover: hover) and (pointer: fine) {
  .vial-option:hover input:enabled + .vial-slot { border-color: var(--blue); }
}
.vial-option input:checked + .vial-slot {
  background: var(--selected);
  border-color: var(--blue);
  box-shadow: inset 0 0 0 1px var(--blue);
}
.vial-option input:focus-visible + .vial-slot { outline: 3px solid var(--blue); outline-offset: 1px; }
.vial-check {
  position: absolute;
  inset: .1875rem .1875rem auto auto;
  display: grid;
  place-items: center;
  inline-size: 1rem;
  block-size: 1rem;
  border-radius: 50%;
  background: var(--blue);
  color: var(--surface);
  font-size: .6875rem;
}
.vial-front {
  padding-top: .375rem;
  text-align: center;
  color: var(--muted);
  font-size: .6875rem;
  font-weight: 500;
}
</style>
