export const pumpState = {
  on: 'Ligada (simulada)',
  off: 'Desligada (simulada)',
  unknown: 'Desconhecida',
}

export const pumpReason = {
  initial: 'Início da alocação',
  history_started: 'Início do registro de períodos',
  od_max: 'OD atingiu ou superou o limite máximo',
  od_min: 'OD atingiu ou ficou abaixo do limite mínimo',
  pause: 'Pausa solicitada',
  resume: 'Retomada solicitada',
  ending: 'Encerramento solicitado',
  reconcile: 'Reconciliação do estado da bomba',
  resume_reconcile: 'Desligamento para retomar o automático',
  confirmation_lost: 'Confirmação perdida ou indisponível',
}

export const commandStatus = {
  pending: 'Aguardando resultado',
  received: 'Recebido pelo simulador',
  executed: 'Executado no simulador',
  rejected: 'Rejeitado pelo simulador',
  expired: 'Expirado no simulador',
  failed: 'Falhou no simulador',
  unknown: 'Sem confirmação',
  superseded: 'Substituído',
}

export const commandAction = command => command.desired_state === 'on' ? 'Ligar' : 'Desligar'
export const isFinal = command => !['pending', 'received'].includes(command.result_status)
export const isOld = (time, now) => !!time && now - Date.parse(time) > 10_000

export function pumpPeriods(transitions, window) {
  return transitions.flatMap((transition, index) => {
    const start = Math.max(window.min, Date.parse(transition.observed_at))
    const next = transitions[index + 1]
    const end = next ? Math.min(window.max, Date.parse(next.observed_at)) : window.max
    return start < end && (transition.paused || transition.confirmed_state === 'on')
      ? [{ ...transition, start, end }]
      : []
  })
}

export const pumpTime = new Intl.DateTimeFormat('pt-BR', { dateStyle: 'short', timeStyle: 'medium' })
export const odValue = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 6 })
