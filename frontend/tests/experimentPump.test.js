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
  export default {
    props: ['readings'],
    render() { return h('chart', { count: this.readings.length }) },
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
  return { type, text, props: {}, children: [], parent: null, focus() {}, addEventListener() {} }
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

test('pump 503 and an outdated GET do not block charts or overwrite a successful pause', async (t) => {
  const root = node('root')
  const start = new Date().toISOString()
  const experiment = { id: 1, name: 'Experimento de teste', vial_id: 1, status: 'active', started_at: start }
  const automatic = { state: 'automatic', ending: false }
  const pausing = { state: 'pausing', ending: false }
  const response = (body, status = 200) => Response.json(body, { status })
  const unavailable = () => response({ detail: 'Banco de dados indisponível.' }, 503)
  let getPump = unavailable
  let readings = []
  let poll
  t.mock.method(globalThis, 'setInterval', (callback, ms) => {
    if (ms === 5000) poll = callback
    return 1
  })
  t.mock.method(globalThis, 'fetch', async (url, options) => {
    const base = '/api/experiments/1'
    if (url === base) return response(experiment)
    if (url === base + '/closure') return response({ state: 'none' })
    if (url === `${base}/pump`) return getPump()
    if (url === `${base}/pump/pause` && options?.method === 'POST') return response(pausing)
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
  const chartCounts = () => descendants(root).filter((el) => el.type === 'chart')
    .map((el) => el.props.count)

  await settle()
  assert.match(text(), /Experimento de teste/)
  assert.match(text(), /Não foi possível atualizar o estado da bomba/)
  assert.deepEqual(chartCounts(), [0, 0, 0])

  readings = [{ generated_at: start, value: 0.7, temperature_celsius: 37 }]
  poll()
  await settle()
  assert.deepEqual(chartCounts(), [1, 1, 1])
  assert.doesNotMatch(text(), /Não foi possível atualizar as leituras/)
  button('Pausar visualização').props.onClick()
  await settle()
  assert.ok(button('Retomar visualização'))

  getPump = () => response(automatic)
  poll()
  await settle()
  const pausePump = button('Pausar bomba')
  assert.ok(pausePump)

  let finishOldGet
  getPump = () => new Promise((resolve) => {
    finishOldGet = () => resolve(response(automatic))
  })
  poll()
  pausePump.props.onClick()
  await settle()
  assert.ok(button('Despausar bomba'))
  finishOldGet()
  await settle()
  assert.ok(button('Despausar bomba'))
  assert.match(text(), /Pausando…/)
  assert.ok(button('Retomar visualização'))
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
        if (url === base + '/pump') return Response.json({ state: 'automatic', ending: false })
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
