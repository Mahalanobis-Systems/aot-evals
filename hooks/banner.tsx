import type { Register } from 'claude-code'

// The banner `aot-evals start` prints. The terminal folds a finished command into a group line
// ("Ran 1 shell command"), and a model asked to paste the output often doesn't, so this mod
// draws the banner itself: on the group line, and on a standalone result row.
const SIGNATURE = 'by Mahal Systems'

function bannerText(tool: string, output: unknown): string | null {
  if (tool !== 'Bash') return null
  const stdout = (output as { stdout?: unknown } | null)?.stdout
  if (typeof stdout !== 'string' || !stdout.includes(SIGNATURE)) return null
  return stdout.replace(/\s+$/, '')
}

function draw($: any, e: any, text: string) {
  const { Box, Text } = $.ui.resolve(e)
  const lines = text.split('\n')
  const art = lines.indexOf(SIGNATURE)
  return (
    <Box flexDirection="column">
      {lines.map((line, i) => (
        <Text key={`l${i}`} color={i < art ? 'cyan' : undefined} bold={i <= art}>
          {line === '' ? ' ' : line}
        </Text>
      ))}
    </Box>
  )
}

export const register: Register = on => {
  on('ui.render', { component: 'ToolResult' }, ($, e, next) => {
    const text = e.props.isErrored ? null : bannerText(e.props.tool, e.props.output)
    return text === null ? next(e) : draw($, e, text)
  })

  on('ui.render', { component: 'ToolGroup' }, async ($, e, next) => {
    if (e.props.isExpanded) return next(e)
    const hit = e.props.calls.find(c => !c.isErrored && bannerText(c.tool, c.output) !== null)
    if (!hit) return next(e)
    const banner = draw($, e, bannerText(hit.tool, hit.output)!)
    if (e.props.calls.length === 1) return banner
    const { Box } = $.ui.resolve(e)
    return (
      <Box flexDirection="column">
        {await next(e)}
        {banner}
      </Box>
    )
  })
}
