// Builds an HTML sheet of Lucide icons (ISC licence; lucide-react is already a dependency of the ProofCam frontend)
// in the deck's colours. Rendered to PNG by headless Chrome and cut into cells by build_assets.py.
// Usage: node icons.mjs <frontend_dir> <out.html> <out.json>
import { pathToFileURL } from 'node:url'
import { readFileSync, writeFileSync } from 'node:fs'
import path from 'node:path'

const [frontend, outHtml, outJson] = process.argv.slice(2)
const COLOURS = { white: '#EEF2F7', blue: '#5B9BFF', green: '#2FD07A', amber: '#F7B23B', red: '#FF5A4E', grey: '#8A94A6' }
const WANT = [
  ['server', 'white'], ['radio-tower', 'white'], ['factory', 'white'], ['solar-panel', 'white'], ['wrench', 'white'],
  ['building-2', 'white'], ['camera', 'blue'], ['scan-search', 'blue'], ['layers', 'blue'], ['scale', 'blue'],
  ['circle-help', 'amber'], ['search-check', 'blue'], ['file-check', 'blue'], ['user-check', 'blue'],
  ['shield-check', 'green'], ['smartphone', 'white'], ['database', 'blue'], ['network', 'blue'], ['list-checks', 'white'],
  ['images', 'white'], ['cable', 'white'], ['plug', 'white'], ['eye', 'blue'], ['circle-check', 'green'],
  ['circle-x', 'red'], ['triangle-alert', 'amber'], ['file-text', 'white'], ['clipboard-check', 'white'],
  ['scan-eye', 'blue'], ['badge-check', 'green'], ['camera', 'white'], ['user-check', 'amber'], ['scale', 'white'],
  ['scan-search', 'white'], ['file-check', 'white'], ['shield-check', 'white'], ['circle-help', 'white'],
  ['layers', 'white'], ['database', 'white'], ['smartphone', 'blue'], ['eye', 'white'], ['network', 'white'],
]
const CELL = 220, ICON = 180, COLS = 8
const cells = []
let html = `<!doctype html><html><head><style>html,body{margin:0;background:transparent}
.g{display:grid;grid-template-columns:repeat(${COLS},${CELL}px);grid-auto-rows:${CELL}px}
.c{display:flex;align-items:center;justify-content:center}</style></head><body><div class="g">`
const ICONS = path.join(frontend, 'node_modules/lucide-react/dist/esm/icons')
// Some names are aliases that re-export another icon module: follow them to the module holding __iconData.
async function load(name) {
  const file = path.join(ICONS, `${name}.mjs`)
  const mod = await import(pathToFileURL(file).href)
  if (mod.__iconData) return mod.__iconData
  const target = readFileSync(file, 'utf8').match(/from '\.\/([\w-]+)\.mjs'/)
  if (target) return load(target[1])
  throw new Error(`no icon data for ${name}`)
}
for (const [i, [name, colour]] of WANT.entries()) {
  const data = await load(name)
  const body = data.node.map(([tag, attrs]) => {
    const a = Object.entries(attrs).filter(([k]) => k !== 'key').map(([k, v]) => `${k}="${v}"`).join(' ')
    return `<${tag} ${a}/>`
  }).join('')
  html += `<div class="c"><svg xmlns="http://www.w3.org/2000/svg" width="${ICON}" height="${ICON}" viewBox="0 0 24 24" fill="none"
    stroke="${COLOURS[colour]}" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round">${body}</svg></div>`
  cells.push({ name, colour, col: i % COLS, row: Math.floor(i / COLS) })
}
html += '</div></body></html>'
writeFileSync(outHtml, html)
writeFileSync(outJson, JSON.stringify({ cell: CELL, cols: COLS, rows: Math.ceil(WANT.length / COLS), cells }, null, 1))
console.log(`${cells.length} icons`)
