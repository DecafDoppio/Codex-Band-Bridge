const { WASI } = require('node:wasi');
const fs = require('node:fs');
const wasi = new WASI({ version: 'preview1', args: [...process.argv.slice(2), '--test-threads=1'], env: process.env, preopens: {} });
WebAssembly.compile(fs.readFileSync(process.argv[2]))
  .then(module => WebAssembly.instantiate(module, wasi.getImportObject()))
  .then(instance => wasi.start(instance))
  .catch(error => { console.error(error.message); process.exitCode = 1; });
