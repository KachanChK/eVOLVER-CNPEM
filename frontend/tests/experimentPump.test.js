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
const router = asModule('export const useRouter = () => ({})')
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
