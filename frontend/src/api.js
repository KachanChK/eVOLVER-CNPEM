export async function request(path, options) {
  let response
  try {
    response = await fetch(`/api${path}`, options)
  } catch {
    throw new Error('Não foi possível conectar à API.')
  }
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    const detail = typeof body?.detail === 'string' ? body.detail : 'Não foi possível concluir a solicitação.'
    throw Object.assign(new Error(detail), { status: response.status })
  }
  return response.status === 204 ? undefined : response.json()
}
