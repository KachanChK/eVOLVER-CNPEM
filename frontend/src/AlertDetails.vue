<script setup>
import { computed } from 'vue'
import { alertTime, describeAlert } from './alerts.js'

const props = defineProps({ alert: { type: Object, required: true } })
const description = computed(() => describeAlert(props.alert))
</script>

<template>
  <div class="alert-details">
    <strong>{{ description.title }}</strong>
    <p>{{ alert.experiment_name }} · Vial {{ alert.vial_id }}</p>
    <p class="muted">{{ description.description }}</p>
    <p v-if="alert.type === 'pump'" class="muted">
      Comando <code translate="no">{{ alert.details.command_id }}</code>
    </p>
    <time class="muted" :datetime="alert.emitted_at">{{ alertTime.format(new Date(alert.emitted_at)) }}</time>
  </div>
</template>
