import { describe, expect, test } from 'claude-code/testing'
import type { On, PromptSubmitInput } from 'claude-code'
import type { Engine } from 'claude-code/testing'

const AGENT = 'a1'
const HANDBACK = `<agent-message from="${AGENT}">[Subagent hand-back] the agent's result`
const USER = { origin: { kind: 'composer' }, wait: false } as const

/**
 * Stands in for the engine beneath the mod. A user message enters or is
 * dropped as `enters` says at the time it arrives. Records what reached the
 * engine and the latest status line.
 */
const engineOf = (on: On) => {
  const world = {
    enters: true,
    entered: [] as Pick<PromptSubmitInput, 'text' | 'context'>[],
    status: undefined as string | undefined,
  }

  on('turn.start', (_, e) => ({ turnId: e.turnId }))
  on('agent.spawn', () => ({ model: 'm', agentId: AGENT }))
  on('agent.list', () => ({
    value: [{ id: AGENT, description: 'task', type: 'general-purpose', status: 'running' }],
  }))
  on('ui.status', (_, e) => {
    world.status = e.text
    return { value: undefined }
  })
  on('prompt.submit', (_, e) => {
    if (!world.enters) {
      return { drop: 'blocked beneath' }
    }

    world.entered.push({ text: e.text, context: e.context })
    return { text: e.text, context: e.context, origin: e.origin }
  })

  return world
}

/** A main turn launches one background agent, whose hand-back the mod holds. */
const holdOne = async ($: Engine) => {
  await $.turn.start({ text: 'go', turnId: 't1' })
  await $.agent.spawn({
    tool_use_id: 'u1',
    prompt: 'do it',
    description: 'task',
    subagentType: 'general-purpose',
    provider: { plugin: 'engine', tier: 'core' },
    parentModel: 'm',
    background: true,
    fork: false,
  })

  const arrival = await $.prompt.submit({ text: HANDBACK, wait: false, origin: { kind: 'peer' } })
  expect(arrival, 'the hand-back is held').toEqual({ drop: 'held' })
}

describe('a user message while messages are held', () => {
  test('dropped beneath the mod, it leaves the held messages pending', async ($, on) => {
    const world = engineOf(on)
    await holdOne($)

    world.enters = false
    const result = await $.prompt.submit({ ...USER, text: 'hi' })

    expect(result.drop).toBe('blocked beneath')
    expect(world.entered).toEqual([])
    expect(world.status).toBe('1 held')
  })

  test('the next message after a drop carries the held messages once', async ($, on) => {
    const world = engineOf(on)
    await holdOne($)

    world.enters = false
    await $.prompt.submit({ ...USER, text: 'hi' })
    world.enters = true
    await $.prompt.submit({ ...USER, text: 'again' })
    await $.prompt.submit({ ...USER, text: 'and again' })

    expect(world.entered).toEqual([
      { text: 'again', context: [HANDBACK] },
      { text: 'and again', context: undefined },
    ])
    expect(world.status).toBeUndefined()
  })

  test('entering, it carries the held messages and leaves nothing pending', async ($, on) => {
    const world = engineOf(on)
    await holdOne($)

    await $.prompt.submit({ ...USER, text: 'hi' })
    await $.prompt.submit({ ...USER, text: 'next' })

    expect(world.entered).toEqual([
      { text: 'hi', context: [HANDBACK] },
      { text: 'next', context: undefined },
    ])
    expect(world.status).toBeUndefined()
  })
})

test('a user message with nothing held passes through unchanged', async ($, on) => {
  const world = engineOf(on)

  const result = await $.prompt.submit({ ...USER, text: 'hi' })

  expect(result).toEqual({ text: 'hi', context: undefined, origin: { kind: 'composer' } })
  expect(world.entered).toEqual([{ text: 'hi', context: undefined }])
})
