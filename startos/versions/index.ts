import { VersionGraph, VersionInfo } from '@start9labs/start-sdk'
const initial = VersionInfo.of({
    version: '0.1.0:10',
    releaseNotes: 'Experimental public preview: supplier resource limits, bounded discovery, pre-work fee checks, payment-price guards and sanitized release metadata.',
    migrations: {},
  })
export const versions = VersionGraph.of({
  current: initial,
  other: [],
})
