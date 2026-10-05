import { buildManifest } from '@start9labs/start-sdk'
import { sdk } from './sdk'
import { versions } from './versions'
import { actions } from './actions'
import { setInterfaces } from './interfaces'
import { manifest as base } from './manifest'
export const manifest = buildManifest(versions, base)
export { main } from './main'
export { actions } from './actions'
export const { createBackup, restoreInit } = sdk.setupBackups(async () => sdk.Backups.ofVolumes('main'))
export const init = sdk.setupInit(versions, actions, setInterfaces, restoreInit)
export const uninit = sdk.setupUninit(versions)
