import * as THREE from 'three'

const material = (color, roughness = .55, metalness = 0) =>
  new THREE.MeshStandardMaterial({ color, roughness, metalness })

const aluminum = material(0xb0bec4, .29, .84)
const fastener = material(0x89979e, .27, .9)
const groove = material(0x36464f, .72, .26)
const tray = material(0x26343a, .42, .24)
const rubber = material(0x20292e, .8)
const cap = material(0x116144, .5)
const fitting = material(0xdde5e6, .34)
const liquid = material(0xa45e1b, .24)
const glass = new THREE.MeshPhysicalMaterial({
  color: 0xbddee4, roughness: .19, transparent: true, opacity: .46, depthWrite: false,
  clearcoat: 1, side: THREE.DoubleSide,
})
const tubing = material(0xc3d9e2, .32)
const gold = material(0xc39a47, .38, .58)
const pcb = material(0x187455, .54)
const port = material(0x41626b, .32, .45)

const cube = new THREE.BoxGeometry(1, 1, 1)
const round = new THREE.CylinderGeometry(1, 1, 1, 28)
const shoulder = new THREE.CylinderGeometry(.69, 1, 1, 28)
const hex = new THREE.CylinderGeometry(1, 1, 1, 6)

function mesh(parent, geometry, surface, x, y, z) {
  const part = new THREE.Mesh(geometry, surface)
  part.position.set(x, y, z)
  parent.add(part)
  return part
}

function box(parent, surface, x, y, z, width, height, depth) {
  const part = mesh(parent, cube, surface, x, y, z)
  part.scale.set(width, height, depth)
  return part
}

function cylinder(parent, surface, x, y, z, radius, height, geometry = round) {
  const part = mesh(parent, geometry, surface, x, y, z)
  part.scale.set(radius, height, radius)
  return part
}

function rail(parent, x, y, z, length, axis) {
  const profile = new THREE.Group()
  parent.add(profile)
  profile.position.set(x, y, z)
  if (axis === 'z') profile.rotation.y = Math.PI / 2
  if (axis === 'y') profile.rotation.z = Math.PI / 2

  box(profile, aluminum, 0, 0, 0, length, .17, .17)
  for (const side of [-1, 1]) {
    box(profile, groove, 0, side * .086, 0, length - .025, .004, .045)
    box(profile, groove, 0, 0, side * .086, length - .025, .045, .004)
    box(profile, aluminum, 0, side * .088, 0, length - .04, .003, .013)
    box(profile, aluminum, 0, 0, side * .088, length - .04, .013, .003)
  }
}

function paint(width, height, draw) {
  const canvas = document.createElement('canvas')
  canvas.width = width
  canvas.height = height
  draw(canvas.getContext('2d'), width, height)
  const texture = new THREE.CanvasTexture(canvas)
  texture.colorSpace = THREE.SRGBColorSpace
  texture.anisotropy = 4
  return texture
}

function vialLabel(parent, number, x, z) {
  const map = paint(256, 128, (context, w, h) => {
    context.fillStyle = '#223139'
    context.fillRect(0, 0, w, h)
    context.font = '700 98px system-ui'
    context.textAlign = 'center'
    context.textBaseline = 'middle'
    context.fillStyle = '#f0f8fa'
    context.fillText(String(number).padStart(2, '0'), w / 2, h / 2)
  })
  const panel = mesh(parent, new THREE.PlaneGeometry(.245, .12),
    new THREE.MeshBasicMaterial({ map }), x, .759, z + .265)
  panel.rotation.x = -Math.PI / 2
}

function chassis(parent) {
  box(parent, tray, 0, .28, 0, 5.29, .14, 3.91)
  box(parent, tray, 0, .10, 2.02, 5.38, .19, .16)
  for (const x of [-2.64, 2.64]) {
    rail(parent, x, .35, 0, 4.15, 'z')
    for (const z of [-1.93, 1.93]) cylinder(parent, rubber, x, .075, z, .19, .15)
    box(parent, aluminum, x, .48, 1.99, .28, .13, .26)
    cylinder(parent, fastener, x, .555, 1.99, .06, .025, hex)
  }
  for (const z of [-2.03, 2.03]) rail(parent, 0, .35, z, 5.47, 'x')

  box(parent, groove, 0, .51, .62, 4.79, .21, 2.69)
  box(parent, tray, 0, .625, .62, 4.82, .065, 2.72)
  box(parent, aluminum, 0, .43, 1.98, 4.81, .035, .07)
}

function controller(parent) {
  box(parent, pcb, 0, .48, -1.29, 4.69, .065, 1.19)
  const traces = paint(1024, 256, (context, w, h) => {
    for (let path = 0; path < 38; path += 1) {
      const x = 28 + path * 25
      const offset = (path % 4 - 1.5) * 16
      context.strokeStyle = path % 3 ? '#79c992' : '#d5ba67'
      context.lineWidth = path % 4 ? 1.5 : 2.5
      context.beginPath()
      context.moveTo(x, 10)
      context.lineTo(x, 67 + path % 6 * 12)
      context.lineTo(x + offset, 108 + path % 6 * 12)
      context.lineTo(x + offset, h - 25)
      context.stroke()
      context.fillStyle = '#d5ba67'
      context.fillRect(Math.max(0, Math.min(w - 6, x + offset - 3)), h - 25, 6, 6)
    }
  })
  const details = mesh(parent, new THREE.PlaneGeometry(4.64, 1.15),
    new THREE.MeshBasicMaterial({ map: traces, transparent: true, depthWrite: false }), 0, .514, -1.29)
  details.rotation.x = -Math.PI / 2

  for (let i = 0; i < 7; i += 1) {
    const x = (i - 3) * .61
    box(parent, pcb, x, .554, -1.42, .42, .052, .48)
    box(parent, rubber, x, .608, -1.42, .19, .061, .21)
    for (const side of [-1, 1]) box(parent, gold, x + side * .153, .593, -1.42, .026, .045, .43)
    box(parent, rubber, x, .581, -.92, .28, .126, .19)
  }
  for (const x of [-2.22, 2.22]) {
    for (const z of [-1.76, -.83]) cylinder(parent, gold, x, .519, z, .044, .035, hex)
    box(parent, port, x, .61, -1.45, .23, .19, .37)
  }
}

function pumpRack(parent) {
  for (const x of [-2.47, 2.47]) {
    rail(parent, x, 1.49, -1.78, 2.29, 'y')
    box(parent, rubber, x, 2.65, -1.78, .18, .045, .18)
    box(parent, aluminum, x, .52, -1.78, .26, .19, .3)
  }
  rail(parent, 0, 2.51, -1.78, 5.10, 'x')
  box(parent, tray, 0, 2.01, -1.72, 4.69, .88, .13)
  box(parent, aluminum, 0, 1.56, -1.72, 4.70, .04, .15)

  return Array.from({ length: 12 }, (_, index) => {
    const x = (index % 6 - 2.5) * .72
    const y = 2.24 - Math.floor(index / 6) * .46
    box(parent, aluminum, x, y, -1.537, .39, .29, .22)
    const head = cylinder(parent, rubber, x, y, -1.36, .161, .18)
    head.rotation.x = Math.PI / 2
    const face = cylinder(parent, groove, x, y, -1.266, .125, .025)
    face.rotation.x = Math.PI / 2
    const hub = cylinder(parent, fastener, x, y, -1.244, .034, .025, hex)
    hub.rotation.x = Math.PI / 2

    return [-.115, .115].map(offset => {
      const tip = cylinder(parent, fitting, x + offset, y + .087, -1.29, .027, .16)
      tip.rotation.x = Math.PI / 2
      return new THREE.Vector3(x + offset, y + .087, -1.205)
    })
  })
}

const knurledCap = new THREE.CylinderGeometry(1, 1, 1, 96)
const capVertices = knurledCap.getAttribute('position')
for (let i = 0; i < capVertices.count; i += 1) {
  const angle = Math.atan2(capVertices.getX(i), capVertices.getZ(i))
  const ridge = 1 - .07 * (1 - Math.cos(24 * angle))
  capVertices.setX(i, capVertices.getX(i) * ridge)
  capVertices.setZ(i, capVertices.getZ(i) * ridge)
}
knurledCap.computeVertexNormals()

function vial(parent, number, x, z, indicator, ports) {
  box(parent, rubber, x, .705, z, .68, .105, .66)
  for (const offset of [-.265, .265]) {
    cylinder(parent, fastener, x + offset, .77, z + .243, .031, .035, hex)
  }
  cylinder(parent, rubber, x, 1.011, z, .234, .555)
  cylinder(parent, tray, x, 1.286, z, .251, .064)
  const ring = cylinder(parent, indicator, x, 1.326, z, .245, .032)
  cylinder(parent, glass, x, 1.478, z, .183, .294)
  cylinder(parent, liquid, x, 1.414, z, .164, .155)
  cylinder(parent, glass, x, 1.649, z, .183, .05, shoulder)
  cylinder(parent, glass, x, 1.689, z, .127, .041)
  cylinder(parent, cap, x, 1.747, z, .193, .126, knurledCap)
  cylinder(parent, cap, x, 1.815, z, .176, .032)
  vialLabel(parent, number, x, z)

  for (const [index, end] of ports.entries()) {
    const tubeX = x + (index ? .078 : -.078)
    cylinder(parent, fitting, tubeX, 1.87, z, .052, .087, hex)
    cylinder(parent, fitting, tubeX, 1.947, z, .033, .075)
    const start = new THREE.Vector3(tubeX, 1.983, z)
    const arch = 2.31 + (z + .36) * .30 + index * .075
    const curve = new THREE.CubicBezierCurve3(start,
      new THREE.Vector3(tubeX, arch + .35, z - .16),
      new THREE.Vector3(end.x, arch, end.z + .68), end)
    const tube = mesh(parent, new THREE.TubeGeometry(curve, 24, .018, 6, false), tubing, 0, 0, 0)
    tube.userData.ignoreHover = true
  }
  return ring
}

export function buildEquipment(vials, indicators) {
  const equipment = new THREE.Group()
  chassis(equipment)
  controller(equipment)
  const ports = pumpRack(equipment)
  const rings = []

  for (const [index, { number, state }] of vials.entries()) {
    const column = index % 4
    const row = Math.floor(index / 4)
    const pump = column * 3 + row
    const group = new THREE.Group()
    group.userData.vialNumber = number
    equipment.add(group)
    rings.push(vial(group, number, (column - 1.5) * 1.05, 1.48 - row * .89, indicators[state], ports[pump]))
  }

  return { equipment, rings }
}

export function buildContactShadow() {
  const map = paint(256, 256, (context, w, h) => {
    const gradient = context.createRadialGradient(w / 2, h / 2, w * .16, w / 2, h / 2, w / 2)
    gradient.addColorStop(0, 'rgba(34, 57, 67, .49)')
    gradient.addColorStop(.63, 'rgba(34, 57, 67, .23)')
    gradient.addColorStop(1, 'rgba(34, 57, 67, 0)')
    context.fillStyle = gradient
    context.fillRect(0, 0, w, h)
  })
  const shadow = new THREE.Mesh(new THREE.PlaneGeometry(8.9, 6.75),
    new THREE.MeshBasicMaterial({ map, transparent: true, depthWrite: false }))
  shadow.rotation.x = -Math.PI / 2
  return shadow
}
