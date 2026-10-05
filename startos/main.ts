import { sdk } from './sdk'
import { configFile, backendKeyFile, gatewayKeyFile, walletSecretFile } from './config'

export const main = sdk.setupMain(async ({ effects }) => {
  // Track edits so a Configure Node action restarts the process.
  await configFile.read().const(effects)
  const key = await backendKeyFile.read().const(effects)
  const wallet = JSON.parse(await walletSecretFile.read().const(effects) || '{}')
  const gatewayKey = await gatewayKeyFile.read().const(effects)
  const initMounts = sdk.Mounts.of().mountVolume({ volumeId: 'main', mountpoint: '/volume', subpath: null, readonly: false })
  const initializer = sdk.SubContainer.of(effects, { imageId: 'main' }, initMounts, 'offence-init')
  await initializer.execFail(['python', '-m', 'offence.runtime', '/volume'], { cwd: '/app', user: 'root' })
  await initializer.destroy()
  const mounts = sdk.Mounts.of()
    .mountVolume({ volumeId: 'main', mountpoint: '/config', subpath: null, readonly: true })
    .mountVolume({ volumeId: 'main', mountpoint: '/data', subpath: 'runtime', readonly: false })
  const sub = sdk.SubContainer.of(effects, { imageId: 'main' }, mounts, 'offence')
  return sdk.Daemons.of(effects).addDaemon('offence', {
    subcontainer: sub,
    exec: {
      command: ['python', '-m', 'offence.cli', 'serve', '--data', '/data', '--config', '/config/config.json', '--host', '0.0.0.0', '--port', '8080'],
      cwd: '/app', user: 'offence', env: { OFFENCE_BACKEND_API_KEY: key || '', OFFENCE_GATEWAY_API_KEY: gatewayKey || '', OFFENCE_STRIKE_API_KEY: wallet.strikeKey || '', OFFENCE_LND_URL: wallet.url || '', OFFENCE_LND_MACAROON_HEX: wallet.macaroon || '', OFFENCE_LND_TLS_CERT_PEM: wallet.certificate || '' },
    },
    ready: { display: 'Offence', fn: () => sdk.healthCheck.checkPortListening(effects, 8080, {
      successMessage: 'Offence is listening; check the dashboard for payment configuration', errorMessage: 'Lab node is not listening',
    }) },
    requires: [],
  })
})
