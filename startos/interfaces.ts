import { sdk } from './sdk'
export const setInterfaces = sdk.setupInterfaces(async ({ effects }) => {
  const host = sdk.MultiHost.of(effects, 'offence')
  const origin = await host.bindPort(8080, { protocol: 'http' })
  const ui = sdk.createInterface(effects, {
    name: 'Offence', id: 'offence', description: 'Lab dashboard and signed peer protocol.',
    type: 'ui', username: null, path: '', query: {}, schemeOverride: null, masked: false,
  })
  return [await origin.export([ui])]
})
