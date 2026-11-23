import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import { test } from 'node:test'
import { compileScript, parse } from 'vue/compiler-sfc'
import { createRenderer, nextTick } from 'vue'

const componentUrl = new URL('../src/ExperimentDetails.vue', import.meta.url)
const { descriptor } = parse(await readFile(componentUrl, 'utf8'), {
  filename: 'ExperimentDetails.vue',
})
const compiled = compileScript(descriptor, { id: 'experiment-details', inlineTemplate: true })
const asModule = (code) => `data:text/javascript,${encodeURIComponent(code)}`
const chart = asModule(`
  import { h } from '${import.meta.resolve('vue')}'
  import { readingPoints } from '${new URL('../src/history.js', import.meta.url).href}'
  export default {
    props: ['readings', 'valueKey'],
    render() {
      const latest = readingPoints(this.readings, this.valueKey).at(-1)?.reading
      return h('chart', { count: this.readings.length, latest })
    },
  }
`)
const router = asModule(`
  export const routes = []
  export const useRouter = () => ({ replace: (route) => routes.push(route) })
`)
const { routes } = await import(router)
const imports = {
  vue: import.meta.resolve('vue'),
  'vue-router': router,
  './TemperatureHistory.vue': chart,
  './api': new URL('./api.js', componentUrl).href,
}
const code = compiled.content.replace(/from (['"])([^'"]+)\1/g, (_, quote, path) => {
  return `from ${JSON.stringify(imports[path] ?? new URL(path, componentUrl).href)}`
})
const { default: ExperimentDetails } = await import(asModule(code))

function node(type, text = '') {
  return {
    type, text, props: {}, children: [], parent: null,
    focus() { this.focused = true },
    addEventListener() {},
  }
}

function remove(child) {
  if (!child.parent) return
  child.parent.children.splice(child.parent.children.indexOf(child), 1)
  child.parent = null
}

// Vue's host hooks let this test exercise the real template without chart canvas or a browser.
const renderer = createRenderer({
  createElement: node,
  createText: (text) => node('#text', text),
  createComment: () => node('#comment'),
  setText: (element, text) => { element.text = text },
  setElementText: (element, text) => {
    element.text = text
    element.children = []
  },
  insert(child, parent, anchor) {
    remove(child)
    const index = anchor ? parent.children.indexOf(anchor) : parent.children.length
    parent.children.splice(index, 0, child)
    child.parent = parent
  },
  remove,
  parentNode: (child) => child.parent,
  nextSibling: (child) => child.parent?.children[child.parent.children.indexOf(child) + 1],
  patchProp: (element, name, _previous, value) => { element.props[name] = value },
})

function visibleText(element) {
  return [element.text, ...element.children.map(visibleText)].join('')
}

function descendants(element) {
  return [element, ...element.children.flatMap(descendants)]
}

const settle = async () => {
  await new Promise(setImmediate)
  await nextTick()
}

test('OD fallback matches the chart until recovery and stale polling cannot restore it', async (t) => {
  const root = node('root')
  const start = new Date().toISOString()
  const experiment = { id: 1, name: 'Experimento de teste', vial_id: 1, status: 'active', started_at: start }
  const automatic = {
    pump: { state: 'automatic', ending: false, confirmed_state: 'on' },
    latest_od: { value: 0.4, generated_at: start },
    od_readings: [{ value: 0.4, generated_at: start }],
    history: { transitions: [], commands: [] },
  }
  const pausedSnapshot = {
    pump: { state: 'paused', ending: false, confirmed_state: 'off', pending_command_id: null },
    latest_od: { value: 0.35, generated_at: start },
    od_readings: [{ value: 0.4, generated_at: start }, { value: 0.35, generated_at: start }],
    history: {
      transitions: [{ reason: 'pause', observed_at: start }],
      commands: [{
        command_id: 'command-1', desired_state: 'off', result_status: 'executed', result_at: start,
      }],
    },
  }
  const response = (body, status = 200) => Response.json(body, { status })
  const unavailable = () => response({ detail: 'Banco de dados indisponível.' }, 503)
  let getPump = unavailable
  let readings = []
  let getOd = () => response(readings)
  let fallbackRequests = 0
  let poll
  t.mock.method(globalThis, 'setInterval', (callback, ms) => {
    if (ms === 5000) poll = callback
    return 1
  })
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    const base = '/api/experiments/1'
    if (url === base) return response(experiment)
    if (url === base + '/closure') return response({ state: 'none' })
    if (url === `${base}/pump/snapshot`) return getPump(options.signal)
    if (url === `${base}/pump/pause` && options?.method === 'POST') {
      getPump = () => response(pausedSnapshot)
      return response({ state: 'pausing', ending: false, pending_command_id: 'command-1' })
    }
    if (url === `${base}/readings/od`) {
      fallbackRequests++
      return getOd()
    }
    if (url.startsWith(`${base}/readings/`) || url === `${base}/temperature-readings`) {
      return response(readings)
    }
    assert.fail(`Unexpected request ${url}`)
  })
  const app = renderer.createApp(ExperimentDetails, { id: '1' })
  app.mount(root)
  t.after(() => app.unmount())
  const text = () => visibleText(root)
  const button = (label) => descendants(root).find(
    (el) => el.type === 'button' && visibleText(el).trim() === label,
  )
  const charts = () => descendants(root).filter((el) => el.type === 'chart')
  const chartCounts = () => charts().map((el) => el.props.count)
  const panelOd = () => descendants(root)
    .find(el => el.type === 'dt' && visibleText(el) === 'Última OD')
    .parent.children.find(el => el.type === 'dd')
  const assertOd = (value, timestamp) => {
    const chartReading = charts()[2].props.latest
    assert.equal(chartReading?.value, value)
    assert.equal(chartReading?.generated_at, timestamp)
    const time = descendants(panelOd()).find(el => el.type === 'time')
    if (timestamp) {
      assert.equal(time.props.datetime, timestamp)
      assert.match(visibleText(panelOd()), new RegExp('^' + String(value).replace('.', ',')))
      assert.equal(visibleText(time), new Intl.DateTimeFormat('pt-BR', {
        dateStyle: 'short', timeStyle: 'medium',
      }).format(new Date(chartReading.generated_at)))
    } else {
      assert.equal(time, undefined)
      assert.equal(visibleText(panelOd()), 'Sem medições')
    }
  }

  await settle()
  assert.match(text(), /Experimento de teste/)
  assert.match(text(), /Não foi possível atualizar o estado da bomba/)
  assert.deepEqual(chartCounts(), [0, 0, 0])

  readings = [{ generated_at: start, value: 0.7, temperature_celsius: 37 }]
  poll()
  await settle()
  assert.deepEqual(chartCounts(), [1, 1, 1])
  assertOd(0.7, start)
  assert.match(text(), /Estado da bombaDesconhecida/)
  assert.match(text(), /Comando pendenteAguardando consulta/)
  assert.equal(button('Pausar bomba'), undefined)
  assert.doesNotMatch(text(), /Não foi possível atualizar as leituras/)

  let finishFallback
  getOd = () => new Promise(resolve => { finishFallback = resolve })
  getPump = () => response(automatic)
  poll()
  await settle()
  assertOd(0.4, start)
  finishFallback(response([{ value: 0.8, generated_at: start }]))
  await settle()
  assertOd(0.4, start)
  const requestsAtRecovery = fallbackRequests
  button('Pausar visualização').props.onClick()
  await settle()
  assert.ok(button('Retomar visualização'))
  const pausePump = button('Pausar bomba')
  assert.ok(pausePump)

  let finishOldGet
  let outdatedSignal
  getPump = (signal) => new Promise((resolve) => {
    outdatedSignal = signal
    finishOldGet = () => resolve(response(automatic))
  })
  poll()
  pausePump.props.onClick()
  await settle()
  assert.ok(button('Despausar bomba'))
  assert.ok(outdatedSignal.aborted)
  assert.deepEqual(chartCounts(), [1, 1, 1])
  assert.ok(button('Retomar visualização'))
  button('Retomar visualização').props.onClick()
  await settle()
  assert.deepEqual(chartCounts(), [1, 1, 2])
  const coherent = text()
  assert.match(coherent, /Última OD0,35/)
  assert.match(coherent, /Bomba pausada/)
  assert.match(coherent, /Desligada \(simulada\)/)
  assert.match(coherent, /Comando pendenteNenhum/)
  assert.match(coherent, /Última mudançaPausa solicitada/)
  assert.match(coherent, /Último resultado registradoDesligar · Executado no simulador/)
  finishOldGet()
  await settle()
  assert.equal(text(), coherent)
  assert.deepEqual(chartCounts(), [1, 1, 2])

  getPump = unavailable
  poll()
  await settle()
  assertOd(0.35, start)
  assert.match(text(), /Bomba pausada/)

  getPump = () => response({ ...pausedSnapshot, latest_od: null, od_readings: [] })
  poll()
  await settle()
  assertOd(undefined, undefined)

  getPump = unavailable
  poll()
  await settle()
  assertOd(undefined, undefined)
  assert.equal(fallbackRequests, requestsAtRecovery)
})



for (const deleting of [false, true]) {
  for (const immediate of [false, true]) {
    const action = deleting ? 'delete' : 'inactivate'
    test('closure ' + action + (immediate ? ' completes immediately' : ' resumes polling after remount'), async (t) => {
      routes.length = 0
      const base = '/api/experiments/1'
      const start = new Date().toISOString()
      const details = {
        id: 1, name: 'Experimento de teste', vial_id: 1, status: 'active', started_at: start,
      }
      const notices = []
      const startLabel = deleting ? 'Excluir' : 'Inativar'
      const inactive = { ...details, status: 'inactive', ended_at: start }
      const complete = { state: 'completed', action, ended_at: start }
      let closure = { state: 'none' }
      let unavailable = false
      let unconfirmedResponse = !deleting && immediate
      let submitted = 0
      let poll
      t.mock.method(globalThis, 'setInterval', (callback, ms) => {
        if (ms === 5000) poll = callback
        return 1
      })
      globalThis.confirm = () => true
      t.after(() => { delete globalThis.confirm })
      t.mock.method(globalThis, 'fetch', async (url, options) => {
        if (options?.method === (deleting ? 'DELETE' : 'POST')) {
          assert.equal(url, deleting ? base : base + '/inactivate')
          submitted++
          if (unconfirmedResponse) {
            unconfirmedResponse = false
            return Response.json(details)
          }
          if (immediate) {
            closure = complete
            return deleting ? new Response(null, { status: 204 }) : Response.json(inactive)
          }
          closure = { state: 'pending', action }
          return Response.json(closure, { status: 202 })
        }
        if (url === base + '/closure') {
          return unavailable ? Response.json({}, { status: 503 }) : Response.json(closure)
        }
        if (url === base + '/pump/snapshot') return Response.json({ pump: { state: 'automatic', ending: false } })
        if (url === base) {
          if (deleting && closure.state === 'completed') return Response.json({}, { status: 404 })
          return Response.json(details)
        }
        return Response.json([])
      })

      let root = node('root')
      let app
      const mount = () => {
        root = node('root')
        app = renderer.createApp(ExperimentDetails, { id: '1', onChanged: (message) => notices.push(message) })
        app.mount(root)
      }
      mount()
      t.after(() => app.unmount())
      const button = (label) => descendants(root).find(
        (el) => el.type === 'button' && visibleText(el).trim() === label,
      )
      await settle()
      await button(startLabel).props.onClick()
      await settle()
      if (!deleting && immediate) {
        assert.match(visibleText(root), /A API não confirmou o encerramento/)
        assert.deepEqual(notices, [])
        await button(startLabel).props.onClick()
        await settle()
      }
      const success = deleting ? 'Experimento excluído da interface.' : 'Experimento inativado. Vial liberado.'
      if (!immediate) {
        assert.match(visibleText(root), /Aguardando a confirmação/)
        assert.ok(!button(startLabel))
        assert.equal(submitted, 1)
        assert.ok(!notices.includes(success))
        assert.deepEqual(routes, [])
        app.unmount()
        mount()
        await settle()
        assert.match(visibleText(root), /O vial continua ocupado/)

        unavailable = true
        poll()
        await settle()
        assert.match(visibleText(root), /Não foi possível consultar o encerramento/)
        assert.ok(!notices.includes(success))

        unavailable = false
        closure = { state: 'unconfirmed', action }
        poll()
        await settle()
        assert.match(visibleText(root), /ficou sem confirmação/)
        const retry = button('Tentar desligar novamente')
        await Promise.all([retry.props.onClick(), retry.props.onClick()])
        await settle()
        assert.equal(submitted, 2)
        assert.ok(!notices.includes(success))
        assert.deepEqual(routes, [])

        closure = complete
        poll()
        await settle()
      }
      assert.equal(notices.filter((message) => message === success).length, 1)
      if (deleting) assert.deepEqual(routes, [{ name: 'home' }])
      else {
        assert.match(visibleText(root), /Vial 1 · Inativo/)
        assert.ok(!button('Inativar'))
      }
    })
  }
}



test('an unconfirmed closure is actionable while initial readings time out', async (t) => {
  const root = node('root')
  const base = '/api/experiments/1'
  const start = new Date().toISOString()
  const details = { id: 1, name: 'Experimento de teste', vial_id: 1, status: 'active', started_at: start }
  const timeouts = new Map()
  let temperatureSignal
  let slow = true
  let poll
  t.mock.method(AbortSignal, 'timeout', (delay) => {
    const controller = new AbortController()
    timeouts.set(controller.signal, { controller, delay })
    return controller.signal
  })
  t.mock.method(globalThis, 'setInterval', (callback, ms) => {
    if (ms === 5000) poll = callback
    return 1
  })
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    if (url === base) return Response.json(details)
    if (url === base + '/closure') return Response.json({ state: 'unconfirmed', action: 'delete' })
    if (url === base + '/pump/snapshot') return Response.json({
      pump: { state: 'automatic', ending: true },
      od_readings: [{ generated_at: start, value: 0.7 }],
    })
    if (url === base + '/temperature-readings' && slow) {
      temperatureSignal = options?.signal
      return new Promise((_resolve, reject) => {
        temperatureSignal?.addEventListener('abort', () => reject(temperatureSignal.reason), { once: true })
      })
    }
    return Response.json([{ generated_at: start, value: 0.7, temperature_celsius: 37 }])
  })

  const app = renderer.createApp(ExperimentDetails, { id: '1' })
  app.mount(root)
  t.after(() => app.unmount())
  await settle()
  assert.doesNotMatch(visibleText(root), /Carregando experimento/)
  const heading = descendants(root).find((el) => el.type === 'h1')
  assert.ok(heading.focused)
  const retry = descendants(root).find((el) => el.type === 'button' &&
    visibleText(el).trim() === 'Tentar desligar novamente')
  assert.ok(retry && !retry.props.disabled)
  assert.ok(descendants(root).some((el) => el.props.role === 'status' &&
    visibleText(el).includes('ficou sem confirmação')))

  const { controller, delay } = timeouts.get(temperatureSignal)
  assert.ok(delay > 0 && delay <= 10000)
  controller.abort(new DOMException('Leitura expirou', 'TimeoutError'))
  await settle()
  assert.match(visibleText(root), /Não foi possível atualizar as leituras/)
  assert.ok(descendants(root).includes(retry))

  slow = false
  poll()
  await settle()
  assert.doesNotMatch(visibleText(root), /Não foi possível atualizar as leituras/)
  assert.deepEqual(descendants(root).filter((el) => el.type === 'chart').map((el) => el.props.count), [1, 1, 1])
})


for (const closureFirst of [false, true]) {
  test('ended_at takes precedence with ' + (closureFirst ? 'early pending' : 'late unconfirmed'), async (t) => {
    routes.length = 0
    const root = node('root')
    const base = '/api/experiments/1'
    const start = new Date().toISOString()
    const details = {
      id: 1, name: 'Experimento de teste', vial_id: 1, status: 'inactive',
      started_at: start, ended_at: start,
    }
    const closure = { state: closureFirst ? 'pending' : 'unconfirmed', action: 'inactivate' }
    let finishDetails
    let finishClosure
    let deletes = 0
    let confirmations = 0
    globalThis.confirm = () => { confirmations++; return true }
    t.after(() => { delete globalThis.confirm })
    t.mock.method(globalThis, 'fetch', async (url, options) => {
      if (url === base && options?.method === 'DELETE') {
        deletes++
        return new Response(null, { status: 204 })
      }
      if (url === base) return new Promise((resolve) => { finishDetails = () => resolve(Response.json(details)) })
      if (url === base + '/closure') {
        return new Promise((resolve) => { finishClosure = () => resolve(Response.json(closure)) })
      }
      if (url === base + '/pump/snapshot') return Response.json({ pump: { state: 'automatic', ending: false } })
      return Response.json([])
    })
    const app = renderer.createApp(ExperimentDetails, { id: '1' })
    app.mount(root)
    t.after(() => app.unmount())
    if (closureFirst) finishClosure()
    else finishDetails()
    await settle()
    if (closureFirst) finishDetails()
    else finishClosure()
    await settle()
    assert.match(visibleText(root), /Vial 1 · Inativo/)
    assert.doesNotMatch(visibleText(root), /O vial continua ocupado|Tentar desligar novamente/)
    const exclude = descendants(root).find((el) => el.type === 'button' &&
      visibleText(el).trim() === 'Excluir')
    assert.ok(exclude)
    await exclude.props.onClick()
    assert.equal(confirmations, 1)
    assert.equal(deletes, 1)
    assert.deepEqual(routes, [{ name: 'home' }])
  })
}


for (const action of ['delete', 'inactivate']) {
  test('an in-flight pump pause allows exactly one ' + action + ' retry', async (t) => {
    routes.length = 0
    const root = node('root')
    const base = '/api/experiments/1'
    const start = new Date().toISOString()
    const details = { id: 1, name: 'Experimento de teste', vial_id: 1, status: 'active', started_at: start }
    const notices = []
    let closure = { state: 'none' }
    let finishPause
    let finishRetry
    let retries = 0
    let poll
    t.mock.method(globalThis, 'setInterval', (callback, ms) => {
      if (ms === 5000) poll = callback
      return 1
    })
    t.mock.method(globalThis, 'fetch', async (url, options) => {
      if (url === base + '/pump/pause' && options?.method === 'POST') {
        return new Promise((resolve) => {
          finishPause = () => resolve(Response.json({ state: 'paused', ending: false }))
        })
      }
      if (options?.method) {
        assert.deepEqual([url, options.method], action === 'delete'
          ? [base, 'DELETE']
          : [base + '/inactivate', 'POST'])
        retries++
        return new Promise((resolve) => {
          finishRetry = () => {
            closure = { state: 'pending', action }
            resolve(Response.json(closure, { status: 202 }))
          }
        })
      }
      if (url === base) return Response.json(details)
      if (url === base + '/closure') return Response.json(closure)
      if (url === base + '/pump/snapshot') return Response.json({ pump: { state: 'automatic', ending: false } })
      return Response.json([])
    })
    const app = renderer.createApp(ExperimentDetails, { id: '1', onChanged: (message) => notices.push(message) })
    app.mount(root)
    t.after(() => app.unmount())
    const button = (label) => descendants(root).find((el) => el.type === 'button' &&
      visibleText(el).trim() === label)

    await settle()
    button('Pausar visualização').props.onClick()
    const pause = button('Pausar bomba').props.onClick()
    await settle()
    assert.ok(button('Pausar bomba').props.disabled)
    closure = { state: 'unconfirmed', action }
    poll()
    await settle()
    const retry = button('Tentar desligar novamente')
    assert.ok(retry && !retry.props.disabled)
    const submitted = retry.props.onClick()
    await retry.props.onClick()
    assert.equal(retries, 1)
    finishRetry()
    await submitted
    assert.match(visibleText(root), /Aguardando a confirmação/)
    assert.deepEqual(notices.filter(Boolean), [])
    assert.deepEqual(routes, [])

    finishPause()
    await pause
    await settle()
    assert.match(visibleText(root), /Aguardando a confirmação/)
    assert.ok(!button('Despausar bomba'))
    assert.ok(button('Retomar visualização'))
    closure = { state: 'completed', action, ended_at: start }
    poll()
    await settle()
    if (action === 'delete') {
      assert.deepEqual(routes, [{ name: 'home' }])
      assert.deepEqual(notices.filter(Boolean), ['Experimento excluído da interface.'])
    } else {
      assert.match(visibleText(root), /Vial 1 · Inativo/)
      assert.deepEqual(notices.filter(Boolean), ['Experimento inativado. Vial liberado.'])
    }
    assert.equal(retries, 1)
  })
}


for (const action of ['pause', 'resume']) {
  test('pump ' + action + ' releases its button after a timeout', async (t) => {
    const root = node('root')
    const base = '/api/experiments/1'
    const details = {
      id: 1, name: 'Experimento de teste', vial_id: 1, status: 'active',
      started_at: new Date().toISOString(),
    }
    const timeouts = new Map()
    let postSignal
    let posts = 0
    const state = action === 'pause' ? 'automatic' : 'paused'
    t.mock.method(AbortSignal, 'timeout', (delay) => {
      const controller = new AbortController()
      timeouts.set(controller.signal, { controller, delay })
      return controller.signal
    })
    t.mock.method(globalThis, 'fetch', async (url, options) => {
      if (url === base + '/pump/' + action && options?.method === 'POST') {
        posts++
        postSignal = options.signal
        return new Promise((_resolve, reject) => {
          postSignal?.addEventListener('abort', () => reject(postSignal.reason), { once: true })
        })
      }
      if (url === base) return Response.json(details)
      if (url === base + '/closure') return Response.json({ state: 'none' })
      if (url === base + '/pump/snapshot') return Response.json({ pump: { state, ending: false } })
      return Response.json([])
    })
    const app = renderer.createApp(ExperimentDetails, { id: '1' })
    app.mount(root)
    t.after(() => app.unmount())
    await settle()
    const label = action === 'pause' ? 'Pausar bomba' : 'Despausar bomba'
    const button = descendants(root).find((el) => el.type === 'button' && visibleText(el).trim() === label)
    const request = button.props.onClick()
    await settle()
    assert.ok(button.props.disabled)
    assert.ok(timeouts.has(postSignal))
    const { controller, delay } = timeouts.get(postSignal)
    assert.ok(delay > 0 && delay <= 10000)
    const duplicate = button.props.onClick()
    assert.equal(posts, 1)
    controller.abort(new DOMException('Comando expirou', 'TimeoutError'))
    await Promise.all([request, duplicate])
    await settle()
    assert.ok(!button.props.disabled)
    assert.ok(descendants(root).some((el) => el.props.role === 'alert' &&
      visibleText(el).includes('A API demorou para responder')))
  })
}
