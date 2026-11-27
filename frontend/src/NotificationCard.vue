<script setup>
import { ref, watchEffect } from 'vue'

const props = defineProps({
  tone: { type: String, default: 'alert' },
  closeLabel: { type: String, required: true },
  duration: { type: Number, default: 0 },
})
const emit = defineEmits(['dismiss'])
const hovered = ref(false)
const focused = ref(false)

watchEffect((onCleanup) => {
  if (!props.duration || hovered.value || focused.value) return
  const timeout = setTimeout(() => emit('dismiss'), props.duration)
  onCleanup(() => clearTimeout(timeout))
})
</script>

<template>
  <article class="panel notification-card" :data-tone="tone"
           @mouseenter="hovered = true" @mouseleave="hovered = false"
           @focusin="focused = true" @focusout="focused = false">
    <slot />
    <button type="button" :aria-label="closeLabel" @click="emit('dismiss')">
      <span aria-hidden="true">×</span>
    </button>
  </article>
</template>
