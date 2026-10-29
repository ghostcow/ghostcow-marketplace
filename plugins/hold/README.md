# hold

A Claude Code mod that batches the completion messages of background agents. The main session often launches several background agents in one turn. Each agent's hand-back message and task notification would otherwise reach Claude as a separate message, one model turn each. The mod holds these messages while the agents run. When all of them have finished cleanly, it sends the held messages to Claude as one message, verbatim and in arrival order.

## Batches

A batch is the set of background agents that the main session launches during one turn. The batch stays open while that turn runs, so agents launched later in the same turn join it. When the turn ends, the batch closes.

The mod holds two kinds of message from a batch's agents: the agent's hand-back message and its task notification.

Claude Code delivers some task notifications as attachments to the next turn instead of as messages. The mod cannot hold those. They reach Claude in the turn that follows, which is usually the release turn.

These agents are excluded from batches, and their messages pass through unchanged:

- forks
- teammates
- workflow agents
- resumed agents
- agents spawned by subagents

## Release

The mod sends the held messages on one of four events.

| Event | What the mod does |
| --- | --- |
| Clean finish | Once the batch has closed and every agent has completed, the mod sends the batch's held messages to Claude as one message. |
| Failure or kill | When an agent fails, is killed, or ends its turn without an answer, the mod sends its batch's held messages at once. |
| User message | When the user sends a message, the mod attaches all held messages to it as context. |
| Esc | When the user interrupts the main turn, the mod keeps all held messages and attaches them to the user's next message. |

After a release, that batch's later messages pass through unchanged. Slash commands release nothing, because a slash command may start no model turn. If Claude Code refuses the release submission, the messages go with the user's next message.

The mod reads agent status every 2 seconds, because agent status changes raise no event a mod sees. An agent that Claude Code no longer lists counts as finished.

## Switching it off

`/hold` switches holding off or back on for the rest of the session. A toast shows the new state; nothing is added to the transcript. Switching it off sends everything held to Claude at once, and the agents launched afterwards pass through. Switching it back on holds the batches of turns that start afterwards.

## Status line

While a batch holds messages, the status line shows `holding N/M`: N agents have finished out of M in holding batches. While messages wait for the user's next message, it shows `N held`.

## Failure behavior

A hook that throws passes its event on unchanged. The message then reaches Claude as it would without the mod.

## Installation

```
/plugin marketplace add ghostcow/ghostcow-marketplace
/plugin install hold@ghostcow-marketplace
```
