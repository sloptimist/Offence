import { FileHelper, z } from '@start9labs/start-sdk'
import { sdk } from './sdk'

export const configFile = FileHelper.json(
  { base: sdk.volumes.main, subpath: 'config.json' },
  z.record(z.string(), z.unknown()),
)
export const backendKeyFile = FileHelper.string(
  { base: sdk.volumes.main, subpath: 'secrets/backend-api-key' },
)

export const gatewayKeyFile = FileHelper.string(
  { base: sdk.volumes.main, subpath: 'secrets/gateway-api-key' },
)

export const walletSecretFile = FileHelper.string(
  { base: sdk.volumes.main, subpath: 'secrets/lnd-wallet' },
)
