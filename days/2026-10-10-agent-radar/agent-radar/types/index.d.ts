export type AgentState = 'running' | 'done' | 'aborted'

export type AgentRec = {
  id: string
  /** `agent.spawn`'s subagentType: Explore, general-purpose, Plan, fork, teammate, a plugin's own… */
  type: string
  description: string
  model?: string
  background: boolean
  startedAt: number
  endedAt?: number
  toolCalls: number
  toolErrors: number
  tokens: number
  state: AgentState
}

export type Radar = {
  agents: AgentRec[]
  /** Bumped by the 1s tick while something runs, so the pane redraws elapsed time. */
  now: number
}

declare module 'claude-code' {
  interface PluginState {
    'agent-radar': { radar: Radar }
  }
}
