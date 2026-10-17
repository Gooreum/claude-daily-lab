import { atom } from 'claude-code'
import type { Lookup } from '../types'
import { ask } from './lens'

export default function register(on: any) {
  on('command.run', { command: 'lens' }, async ($: any, e: any) => ask($, e))
}
