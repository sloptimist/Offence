import { setupManifest } from '@start9labs/start-sdk'

export const manifest = setupManifest({
  id: 'offence',
  title: 'Offence',
  license: 'MIT',
  packageRepo: 'https://github.com/smallblocks/offence',
  upstreamRepo: 'https://github.com/smallblocks/offence',
  marketingUrl: 'https://offence.ai',
  donationUrl: null,
  docsUrls: [],
  description: {
    short: 'Peer discovery and streamed inference on a permissionless lab network.',
    long: 'Run an independent inference provider connected to a GPU server on your network. ' +
      'Discover signed model offers, choose providers, and test incremental delivery. ' +
      'Experimental software: model accuracy is a seller claim, and buyers requiring execution proofs must refuse. ' +
      'Payment configuration is explicit; the agent gateway supports free experiments only.',
  },
  images: {
    main: {
      source: { dockerBuild: { dockerfile: 'Dockerfile', workdir: '.' } },
      arch: ['x86_64', 'aarch64'],
      emulateMissingAs: null,
      nvidiaContainer: false,
    },
  },
  volumes: ['main'],
  dependencies: {},
  hardwareRequirements: { ram: 512 },
})
