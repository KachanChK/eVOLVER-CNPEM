import * as THREE from 'three'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import { experimentCode } from '../experimentCode.js'
import { buildContactShadow, buildEquipment } from './equipment.js'

export const vialStates = {
  free: { label: 'Livre', color: 0x71828a },
  used: { label: 'Em uso', color: 0x14aa67 },
}

export function mountViewer(root, initialVials) {
  const canvas = root.querySelector('#equipment')
  const message = root.querySelector('#viewer-message')
  const controls = root.querySelector('#rotation-help')
  const card = root.querySelector('#vial-card')
  const cardNumber = root.querySelector('#vial-card-number')
  const cardState = root.querySelector('#vial-card-state')
  const cardExperiment = root.querySelector('#vial-card-experiment')
  let vials = initialVials
  let renderer
  try {
    renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true })
  } catch (error) {
    message.textContent = 'Não foi possível carregar a maquete 3D. Tente em um navegador com WebGL 2.'
    console.error(error)
    return
  }

  const listeners = new AbortController()
  const options = { signal: listeners.signal }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.toneMapping = THREE.ACESFilmicToneMapping
  const scene = new THREE.Scene()
  let environment
  scene.environmentIntensity = .8

  function lightEnvironment() {
    environment?.dispose()
    const studio = new RoomEnvironment()
    const pmrem = new THREE.PMREMGenerator(renderer)
    environment = pmrem.fromScene(studio, .06)
    scene.environment = environment.texture
    pmrem.dispose()
    studio.dispose()
  }

  lightEnvironment()

  const indicators = Object.fromEntries(Object.entries(vialStates).map(([state, { color }]) => [state,
    new THREE.MeshStandardMaterial({ color, emissive: color, emissiveIntensity: state === 'used' ? .38 : 0 }),
  ]))
  const { equipment, rings } = buildEquipment(vials, indicators)
  scene.add(buildContactShadow(), equipment)
  scene.add(new THREE.HemisphereLight(0xeaf5ff, 0x758588, .86))
  const key = new THREE.DirectionalLight(0xfff1df, 1.65)
  key.position.set(-4, 7, 4)
  const fill = new THREE.DirectionalLight(0xd5ebff, 1.1)
  fill.position.set(3, 4, -5)
  scene.add(key, fill)

  const target = new THREE.Vector3(0, 1.19, 0)
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, .1, 50)
  const raycaster = new THREE.Raycaster()
  const pointer = new THREE.Vector2()
  let angle = .56
  let frame = 0
  let drag = null
  let hoveredNumber

  function render() {
    frame = 0
    camera.position.set(8 * Math.sin(angle), target.y + 5.1, 8 * Math.cos(angle))
    camera.lookAt(target)
    renderer.render(scene, camera)
  }

  function requestRender() {
    if (!frame) frame = requestAnimationFrame(render)
  }

  function resize() {
    const { clientWidth: width, clientHeight: height } = canvas
    if (!width || !height) return
    clearHover()
    const aspect = width / height
    const halfHeight = Math.max(3.15, 4.05 / aspect)
    camera.left = -halfHeight * aspect
    camera.right = halfHeight * aspect
    camera.top = halfHeight
    camera.bottom = -halfHeight
    camera.updateProjectionMatrix()
    renderer.setSize(width, height, false)
    requestRender()
  }

  function rotate(delta) {
    angle = (angle + delta) % (2 * Math.PI)
    requestRender()
  }

  function clearHover() {
    hoveredNumber = undefined
    card.hidden = true
  }

  function updateCard() {
    const { number, experimentId, state } = vials[hoveredNumber - 1]
    cardNumber.textContent = `Vial ${String(number).padStart(2, '0')}`
    cardState.textContent = vialStates[state].label
    cardExperiment.hidden = experimentId === null
    cardExperiment.textContent = experimentId === null ? '' : experimentCode(experimentId)
  }

  function inspectVial(event) {
    if (event.pointerType !== 'mouse' || frame) return
    const { left, top, width, height } = canvas.getBoundingClientRect()
    const x = event.clientX - left
    const y = event.clientY - top
    pointer.set(2 * x / width - 1, 1 - 2 * y / height)
    raycaster.setFromCamera(pointer, camera)
    const hit = raycaster.intersectObject(equipment).find(({ object }) => !object.userData.ignoreHover)
    const number = hit?.object.parent.userData.vialNumber
    if (number === hoveredNumber) return
    if (number === undefined) {
      clearHover()
      return
    }

    hoveredNumber = number
    updateCard()
    card.hidden = false
    const right = x + 10
    const leftOfPointer = x - card.offsetWidth - 10
    card.style.left = `${Math.max(8, right + card.offsetWidth <= width - 8 ? right : leftOfPointer)}px`
    card.style.top = `${Math.max(8, Math.min(y - 14, height - 8 - card.offsetHeight))}px`
  }

  canvas.addEventListener('pointerdown', event => {
    if (!event.isPrimary || event.button !== 0) return
    clearHover()
    drag = { pointer: event.pointerId, x: event.clientX }
    canvas.setPointerCapture(event.pointerId)
  }, options)

  canvas.addEventListener('pointermove', event => {
    if (!drag) {
      inspectVial(event)
      return
    }
    if (drag?.pointer !== event.pointerId) return
    rotate((drag.x - event.clientX) * 2 * Math.PI / Math.min(canvas.clientWidth, 760))
    drag.x = event.clientX
  }, options)

  canvas.addEventListener('pointerleave', event => {
    if (!card.contains(event.relatedTarget)) clearHover()
  }, options)
  card.addEventListener('pointerleave', event => {
    clearHover()
    if (event.relatedTarget === canvas) inspectVial(event)
  }, options)
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') card.hidden = true
  }, options)

  canvas.addEventListener('lostpointercapture', event => {
    if (drag?.pointer === event.pointerId) drag = null
  }, options)

  canvas.addEventListener('keydown', event => {
    if (event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return
    if (event.key !== 'ArrowLeft' && event.key !== 'ArrowRight') return
    event.preventDefault()
    clearHover()
    rotate(event.key === 'ArrowLeft' ? .16 : -.16)
  }, options)

  canvas.addEventListener('webglcontextlost', () => {
    clearHover()
    message.textContent = 'A visualização 3D foi interrompida. Recarregue a página se o modelo não reaparecer.'
    message.hidden = false
    controls.hidden = true
    canvas.hidden = true
  }, options)

  canvas.addEventListener('webglcontextrestored', () => {
    lightEnvironment()
    showViewer()
  }, options)

  function showViewer() {
    message.hidden = true
    canvas.hidden = false
    controls.hidden = false
    resize()
  }

  showViewer()
  const resizeObserver = new ResizeObserver(resize)
  resizeObserver.observe(canvas)
  return {
    updateVials(nextVials) {
      vials = nextVials
      for (const [index, { state }] of vials.entries()) rings[index].material = indicators[state]
      if (!card.hidden) updateCard()
      if (!canvas.hidden) requestRender()
    },
    dispose() {
      listeners.abort()
      resizeObserver.disconnect()
      cancelAnimationFrame(frame)
      environment.dispose()
      renderer.dispose()
      renderer.forceContextLoss()
    },
  }
}
