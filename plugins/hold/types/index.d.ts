/**
 * The background agents one main-loop turn launched.
 *
 * `isOpen`: the launching turn is still running, so more agents may join.
 * `isHolding`: completion notices of its agents are held rather than passed on.
 * `ended`: agents whose status shows them completed, failed or killed. `held`: the agents' hand-back
 * messages and task notifications, verbatim, in arrival order.
 */
export type Batch = {
  isOpen: boolean
  isHolding: boolean
  members: string[]
  ended: string[]
  held: string[]
}

/**
 * `mainTurnId`: the running main-loop turn, or null while idle.
 * `batches`: keyed by the id of the turn that launched them.
 * `pending`: released messages that go to Claude with the user's next message.
 * `isOff`: `/hold` switched holding off, so no new batch forms.
 */
export type Hold = {
  mainTurnId: string | null
  batches: Record<string, Batch>
  pending: string[]
  isOff?: boolean
}

declare module 'claude-code' {
  interface PluginState {
    'hold': { hold: Hold }
  }
}
