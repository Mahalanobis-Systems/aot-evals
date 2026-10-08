import { expect, test } from 'claude-code/testing'

const BANNER = `    ___   ____  ______
   /   | / __ \\/_  __/
/_/  |_\\____/ /_/

by Mahal Systems

I'll build tests for one of your agents in two phases.`

const row = (stdout: string) => ({
  component: 'ToolResult' as const,
  requestId: 'toolu_1',
  props: { tool_use_id: 'toolu_1', tool: 'Bash', output: { stdout, stderr: '' }, isErrored: false },
})

const SURFACES = ['terminal', 'desktop'] as const

test('draws the whole banner when aot-evals start prints it', async ($, on) => {
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>folded by the engine</Text>
  })
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ plugin: 'aot-evals', surface, ...row(BANNER) })
    expect(await ui.find({ type: 'Text', text: /\/_\/  \|_/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /by Mahal Systems/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /two phases/ })).toBeDefined()
    expect(await ui.find({ type: 'Text', text: /folded by the engine/ })).toBeUndefined()
    await ui.unmount()
  }
})

test('leaves every other result to the engine', async ($, on) => {
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>folded by the engine</Text>
  })
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ plugin: 'aot-evals', surface, ...row('total 8\nREADME.md') })
    expect(await ui.find({ type: 'Text', text: /folded by the engine/ })).toBeDefined()
    await ui.unmount()
  }
})

const group = (stdout: string, isExpanded = false) => ({
  component: 'ToolGroup' as const,
  requestId: 'group_1',
  props: {
    isActive: false,
    isExpanded,
    calls: [{ tool_use_id: 'toolu_1', tool: 'Bash', input: { command: 'aot-evals start' },
              isRunning: false, isErrored: false, isInterrupted: false,
              output: { stdout, stderr: '' } }],
  },
})

test('draws the banner on the folded "Ran 1 shell command" line', async ($, on) => {
  on('ui.render', ($, e) => {
    const { Text } = $.ui.resolve(e)
    return <Text>folded by the engine</Text>
  })
  for (const surface of SURFACES) {
    const ui = await $.ui.mount({ plugin: 'aot-evals', surface, ...group(BANNER) })
    expect(await ui.find({ type: 'Text', text: /by Mahal Systems/ })).toBeDefined()
    await ui.unmount()
    const other = await $.ui.mount({ plugin: 'aot-evals', surface, ...group('total 8') })
    expect(await other.find({ type: 'Text', text: /folded by the engine/ })).toBeDefined()
    await other.unmount()
  }
})
