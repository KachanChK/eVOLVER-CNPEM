import { nextTick, reactive } from 'vue'

const POLL_INTERVAL = 1000
const NOTICE_DURATION = 5000

export function createAlertFeed(request, isHistoryOpen, timer = globalThis) {
  const state = reactive({
    items: [], notices: [], hasUnread: false, ready: false, error: '',
    nextBefore: null, loadingOlder: false, clearing: false,
  })
  let cursor = null
  let archiveCursor = 0
  let readCursor = 0
  let polling = false
  let interval
  let stopped = false
  const noticeTimers = new Map()

  function dismiss(id) {
    timer.clearTimeout(noticeTimers.get(id))
    noticeTimers.delete(id)
    state.notices = state.notices.filter((alert) => alert.id !== id)
  }

  function merge(items, { older = false } = {}) {
    const combined = older ? [...items, ...state.items] : [...state.items, ...items]
    const visible = combined.filter((alert) => alert.id > archiveCursor)
    state.items = [...new Map(visible.map((alert) => [alert.id, alert])).values()]
      .sort((a, b) => b.id - a.id)
  }

  function archiveThrough(id) {
    archiveCursor = Math.max(archiveCursor, id)
    if (state.nextBefore <= archiveCursor) state.nextBefore = null
  }

  function post(action, id) {
    return request('/alerts/' + action, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cursor: id }),
      signal: AbortSignal.timeout(5000),
    })
  }

  async function poll() {
    if (polling || stopped) return
    polling = true
    try {
      const query = cursor === null ? '' : '?after=' + cursor
      const page = await request('/alerts' + query, { signal: AbortSignal.timeout(3000) })
      if (stopped) return
      if (cursor === null) state.nextBefore = page.next_before
      archiveThrough(page.archived_through)
      const updates = new Map(page.open_missing.map((alert) => [alert.id, alert]))
      const displayed = state.items.filter((alert) => updates.has(alert.id))
        .map((alert) => updates.get(alert.id))
      merge([...page.items, ...page.new, ...displayed])
      state.notices = state.notices.map((alert) => updates.get(alert.id) ?? alert)
      for (const alert of page.new) {
        if (alert.id <= archiveCursor) continue
        state.notices.push(alert)
        noticeTimers.set(alert.id, timer.setTimeout(() => dismiss(alert.id), NOTICE_DURATION))
      }
      cursor = page.cursor
      state.ready = true
      state.error = ''
      state.hasUnread = page.has_unread
      const shown = state.items[0]?.id ?? 0
      if (isHistoryOpen() && page.has_unread && shown > readCursor) {
        await nextTick()
        if (!stopped && isHistoryOpen()) {
          await post('read', shown)
          readCursor = shown
        }
      }
    } catch {
      if (!stopped) state.error = 'A atualização dos alertas foi interrompida. Tentando reconectar…'
    } finally {
      polling = false
    }
  }

  async function loadOlder() {
    if (!state.nextBefore || state.loadingOlder) return
    state.loadingOlder = true
    try {
      const page = await request('/alerts?before=' + state.nextBefore, {
        signal: AbortSignal.timeout(3000),
      })
      archiveThrough(page.archived_through)
      state.nextBefore = page.next_before > archiveCursor ? page.next_before : null
      merge(page.items, { older: true })
    } finally {
      state.loadingOlder = false
    }
  }

  async function clear() {
    const confirmed = state.items[0]?.id
    if (!confirmed || state.clearing) return
    state.clearing = true
    try {
      await post('clear', confirmed)
      archiveThrough(confirmed)
      merge([])
      void poll()
    } finally {
      state.clearing = false
    }
  }

  return {
    state, poll, dismiss, loadOlder, clear,
    start() {
      void poll()
      interval = timer.setInterval(poll, POLL_INTERVAL)
    },
    stop() {
      stopped = true
      timer.clearInterval(interval)
      for (const id of noticeTimers.keys()) dismiss(id)
    },
  }
}

const labels = { temperature: 'Temperatura', ph: 'pH', od: 'OD' }
const number = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 6 })
export const alertTime = new Intl.DateTimeFormat('pt-BR', {
  dateStyle: 'short', timeStyle: 'medium',
})

export function describeAlert(alert) {
  const details = alert.details
  if (alert.type === 'missing_data') {
    return {
      title: details.metrics.length === 3 ? 'Sem dados do vial' : 'Leituras em atraso',
      description: 'Aguardando leituras de ' + details.metrics.map((metric) => labels[metric]).join(', '),
    }
  }
  if (alert.type === 'pump') {
    const failed = details.status === 'failed'
    const action = details.action === 'turn_on' ? 'Ligar o grupo' : 'Desligar o grupo'
    const reasons = {
      simulation_error: 'falha simulada', expired: 'comando expirado',
      timeout: 'prazo de confirmação encerrado',
    }
    return {
      title: failed ? 'Falha no grupo de bombas' : 'Comando das bombas sem confirmação',
      description: action + ' · ' + (reasons[details.reason_code] ?? details.reason_code),
    }
  }
  const unit = details.unit ? '\u00a0' + details.unit : ''
  return {
    title: labels[alert.type] + ' fora da faixa',
    description: number.format(details.value) + unit + ' · Faixa de ' +
      number.format(details.minimum) + ' a ' + number.format(details.maximum) + unit,
  }
}
