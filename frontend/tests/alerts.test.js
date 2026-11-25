import assert from 'node:assert/strict'
import { test } from 'node:test'
import { createAlertFeed, describeAlert } from '../src/alerts.js'

const alert = (id, metrics = ['od']) => ({ id, type: 'missing_data', details: { metrics } })
const page = (items, overrides = {}) => ({
  items,
  next_before: null,
  new: [],
  open_missing: [],
  cursor: items[0]?.id ?? 0,
  archived_through: 0,
  has_unread: !!items.length,
  ...overrides,
})

function clock() {
  let now = 0
  let id = 0
  const timeouts = new Map()
  return {
    setTimeout(callback, delay) {
      timeouts.set(++id, { at: now + delay, callback })
      return id
    },
    clearTimeout(id) { timeouts.delete(id) },
    clearInterval() {},
    advance(milliseconds) {
      now += milliseconds
      for (const [id, { at, callback }] of timeouts) {
        if (at <= now) {
          timeouts.delete(id)
          callback()
        }
      }
    },
  }
}

test('initial history stays silent, reconnection resumes the cursor and each card expires on time', async () => {
  const timer = clock()
  const requests = []
  const replies = [
    page([alert(1)]),
    new Error('offline'),
    page([alert(3), alert(2), alert(1)], { new: [alert(2), alert(3)] }),
    page([alert(4)], { new: [alert(4)], open_missing: [alert(2, ['temperature', 'ph', 'od'])] }),
  ]
  const feed = createAlertFeed(async (path) => {
    requests.push(path)
    const response = replies.shift()
    if (response instanceof Error) throw response
    return response
  }, () => false, timer)
  await feed.poll()
  assert.equal(feed.state.hasUnread, true)
  assert.deepEqual(feed.state.notices, [])
  await feed.poll()
  assert.ok(feed.state.error)
  await feed.poll()
  assert.equal(feed.state.error, '')
  assert.deepEqual(feed.state.notices.map(({ id }) => id), [2, 3])
  timer.advance(1000)
  await feed.poll()
  assert.deepEqual(requests, ['/alerts', '/alerts?after=1', '/alerts?after=1', '/alerts?after=3'])
  assert.equal(describeAlert(feed.state.notices[0]).title, 'Sem dados do vial')
  assert.equal(describeAlert(feed.state.items.find(({ id }) => id === 2)).title, 'Sem dados do vial')
  feed.dismiss(3)
  timer.advance(3999)
  assert.deepEqual(feed.state.notices.map(({ id }) => id), [2, 4])
  timer.advance(1)
  assert.deepEqual(feed.state.notices.map(({ id }) => id), [4])
  timer.advance(1000)
  assert.deepEqual(feed.state.notices, [])
})

test('read follows navigation and clear keeps alerts that arrive during confirmation', async () => {
  let showHistory = false
  let finishClear
  const writes = []
  const replies = [
    page([alert(10)], { next_before: 10 }),
    page([alert(9)]),
    page([alert(10)]),
    page([alert(11), alert(10)], { new: [alert(11)] }),
    page([alert(11)], { archived_through: 10, has_unread: false }),
  ]
  const feed = createAlertFeed(async (path, options) => {
    if (!options.method) return replies.shift()
    writes.push([path, JSON.parse(options.body).cursor])
    if (path.endsWith('/clear')) await new Promise((resolve) => { finishClear = resolve })
  }, () => showHistory, clock())
  await feed.poll()
  await feed.loadOlder()
  assert.deepEqual(feed.state.items.map(({ id }) => id), [10, 9])
  assert.deepEqual(writes, [])
  showHistory = true
  await feed.poll()
  assert.equal(feed.state.hasUnread, true)
  const confirmation = feed.clear()
  await feed.poll()
  finishClear()
  await confirmation
  assert.deepEqual(feed.state.items.map(({ id }) => id), [11])
  assert.deepEqual(writes, [
    ['/alerts/read', 10], ['/alerts/clear', 10], ['/alerts/read', 11],
  ])
  assert.equal(feed.state.hasUnread, false)
})
