import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { Batch, Hold } from '../types'

const hold = atom({ plugin: 'hold', key: 'hold' } as const, {
  mainTurnId: null,
  batches: {},
  pending: [],
} as Hold)

const HELD_REASON = 'held'

const tagOf = (text: string, tag: string) =>
  text.match(new RegExp(`<${tag}>([^<]*)</${tag}>`))?.[1]?.trim()

/** The agent a `[Subagent hand-back]` message comes from, else undefined. */
const handbackSenderOf = (text: string) =>
  text.match(/^\s*<agent-message from="([^"]+)">\s*\[Subagent hand-back\]/)?.[1]

const ENDED = ['completed', 'failed', 'killed']
const FAILED = ['failed', 'killed']

const batchKeyOf = (s: Hold, agentId: string) =>
  Object.keys(s.batches).find(key => s.batches[key]?.members.includes(agentId))

const withBatch = (s: Hold, key: string, batch: Batch): Hold => ({
  ...s,
  batches: { ...s.batches, [key]: batch },
})

const withoutBatch = (s: Hold, key: string): Hold => {
  const { [key]: _, ...batches } = s.batches
  return { ...s, batches }
}

/** Ends holding for one batch: its agents' later messages pass through. */
const stopHolding = (b: Batch): Batch => ({ ...b, isHolding: false, held: [] })

/**
 * Drops batches that hold nothing and take no more agents. An open batch that
 * stopped holding stays, so agents its turn launches later are not held.
 */
const pruned = (s: Hold): Hold => ({
  ...s,
  batches: Object.fromEntries(Object.entries(s.batches).filter(([, b]) => b.isHolding || b.isOpen)),
})

const showStatus = async ($: EngineInterface) => {
  const s = await read($, hold)
  const holding = Object.values(s.batches).filter(b => b.isHolding && b.members.length > 0)
  const finished = holding.reduce((n, b) => n + b.ended.length, 0)
  const members = holding.reduce((n, b) => n + b.members.length, 0)

  if (s.pending.length > 0) {
    $.ui.status(`${s.pending.length} held`)
  } else if (holding.some(b => b.held.length > 0)) {
    $.ui.status(`holding ${finished}/${members}`)
  } else {
    $.ui.status(undefined)
  }
}

/**
 * Sends the held messages to Claude as one message, verbatim and in arrival
 * order. A refused submission keeps them as pending, so they go with the
 * user's next message.
 */
const release = ($: EngineInterface, texts: string[]) => {
  if (texts.length === 0) {
    return
  }

  void $.prompt.submit({ text: texts.join('\n\n') }).then(async result => {
    if (result.drop !== undefined) {
      await update($, hold, s => ({ ...s, pending: [...s.pending, ...texts] }))
      await showStatus($)
    }
  })
}

type Arrival = { agentId: string; text: string; kind: 'handback' | 'notice' }

/**
 * Takes one agent message into its batch: `hold` keeps it for later, `pass`
 * sends it on unchanged as the message is no holding batch's.
 */
const intake = async ($: EngineInterface, arrival: Arrival) => {
  let action = 'pass' as 'pass' | 'hold'

  await update($, hold, s => {
    action = 'pass'
    const key = batchKeyOf(s, arrival.agentId)
    const b = key === undefined ? undefined : s.batches[key]

    if (key === undefined || b === undefined || !b.isHolding) {
      return s
    }

    action = 'hold'
    return withBatch(s, key, { ...b, held: [...b.held, arrival.text] })
  })

  await showStatus($)
  return action
}

/**
 * Brings each holding batch up to date with its agents' status. An agent has
 * ended when its status is completed, failed or killed, or when the engine no
 * longer lists it. A failed or killed agent releases its batch at once; a
 * closed batch whose agents have all ended releases.
 */
const settle = async ($: EngineInterface) => {
  const s0 = await read($, hold)

  if (!Object.values(s0.batches).some(b => b.isHolding && b.members.length > 0)) {
    return
  }

  const statusOf = new Map((await $.agent.list()).map(a => [a.id, a.status as string]))
  const hasEnded = (id: string) => !statusOf.has(id) || ENDED.includes(statusOf.get(id) ?? '')
  const hasFailed = (id: string) => FAILED.includes(statusOf.get(id) ?? '')
  let released: string[] = []

  await update($, hold, s => {
    released = []
    const batches: Record<string, Batch> = {}

    for (const [key, b] of Object.entries(s.batches)) {
      if (!b.isHolding) {
        batches[key] = b
        continue
      }

      const ended = b.members.filter(hasEnded)
      const isDone = b.members.some(hasFailed) || (!b.isOpen && ended.length === b.members.length)

      if (isDone) {
        released = [...released, ...b.held]
        batches[key] = stopHolding({ ...b, ended })
      } else {
        batches[key] = { ...b, ended }
      }
    }

    return pruned({ ...s, batches })
  })

  release($, released)
  await showStatus($)
}

// A hook that fails passes its event on unchanged: a message reaches Claude
// as it would without this mod.
export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const result = await next(e)
    await showStatus($)
    // Agent status changes raise no event a mod sees, so holding batches are
    // checked on a timer.
    $.clock.every(2000, () => settle($).catch(() => undefined))
    return result
  })

  on('turn.start', async ($, e, next) => {

    if (e.agentId === undefined) {
      await update($, hold, s => ({ ...s, mainTurnId: e.turnId }))
    }

    return next(e)
  })

  on('agent.spawn', async ($, e, next) => {
    const result = await next(e)
    const isBatched =
      e.parentAgentId === undefined &&
      e.background &&
      !e.fork &&
      !e.isTeammate &&
      e.workflow === undefined &&
      e.resume === undefined

    if (isBatched && result.agentId !== undefined) {
      const agentId = result.agentId
      await update($, hold, s => {
        if (s.mainTurnId === null) {
          return s
        }

        const b = s.batches[s.mainTurnId] ?? {
          isOpen: true,
          isHolding: true,
          members: [],
          ended: [],
          held: [],
        }

        return withBatch(s, s.mainTurnId, { ...b, members: [...b.members, agentId] })
      })
    }

    return result
  }).catch(($, e, next) => next(e))

  on('turn.complete', async ($, e, next) => {

    if (e.agentId !== undefined) {
      // An agent turn that ends without an answer is a failure.
      if (e.reason !== 'answer') {
        const agentId = e.agentId
        let released: string[] = []
        await update($, hold, s => {
          released = []
          const key = batchKeyOf(s, agentId)
          const b = key === undefined ? undefined : s.batches[key]

          if (key === undefined || b === undefined || !b.isHolding) {
            return s
          }

          released = b.held
          return pruned(withBatch(s, key, stopHolding(b)))
        })
        release($, released)
        await showStatus($)
      }

      return next(e)
    }

    const turnId = e.turnId

    await update($, hold, s => {
      let state: Hold = { ...s, mainTurnId: null }

      if (e.isAborted) {
        // A submission right after an interrupt is refused, so the held
        // messages go with the user's next message.
        const held = Object.values(state.batches).flatMap(b => (b.isHolding ? b.held : []))
        state = {
          ...state,
          pending: [...state.pending, ...held],
          batches: Object.fromEntries(
            Object.entries(state.batches).map(([key, b]) => [key, stopHolding(b)]),
          ),
        }
      }

      const b = state.batches[turnId]

      if (b === undefined) {
        return pruned(state)
      }

      if (!b.isHolding || b.members.length === 0) {
        return pruned(withoutBatch(state, turnId))
      }

      return pruned(withBatch(state, turnId, { ...b, isOpen: false }))
    })

    const result = await next(e)
    await settle($)
    return result
  })

  on('prompt.submit', async ($, e, next) => {

    const sender = e.origin.kind === 'peer' ? handbackSenderOf(e.text) : undefined
    const noticeAgent = e.origin.kind === 'task-notification' ? tagOf(e.text, 'task-id') : undefined
    const arrival: Arrival | undefined =
      sender !== undefined
        ? { agentId: sender, text: e.text, kind: 'handback' }
        : noticeAgent !== undefined
          ? { agentId: noticeAgent, text: e.text, kind: 'notice' }
          : undefined

    if (arrival !== undefined) {
      const action = await intake($, arrival)
      if (action === 'pass') {
        return next(e)
      }

      void settle($).catch(() => undefined)
      return { drop: HELD_REASON }
    }

    const isUsers = e.origin.kind === 'composer' || e.origin.kind === 'bridge' || e.origin.kind === 'sdk'

    // A slash command may start no model turn, so held messages stay held.
    if (!isUsers || e.command !== undefined) {
      return next(e)
    }

    let released: string[] = []
    await update($, hold, s => {
      const held = Object.values(s.batches).flatMap(b => (b.isHolding ? b.held : []))
      released = [...s.pending, ...held]
      return pruned({
        ...s,
        pending: [],
        batches: Object.fromEntries(
          Object.entries(s.batches).map(([key, b]) => [key, b.isHolding ? stopHolding(b) : b]),
        ),
      })
    })
    await showStatus($)

    if (released.length === 0) {
      return next(e)
    }

    return next({ ...e, context: [...(e.context ?? []), ...released] })
  }).catch(($, e, next) => next(e))
}
