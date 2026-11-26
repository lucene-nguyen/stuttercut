import { describe, expect, it } from 'vitest'

import { errorReport } from './report'

describe('UI error report', () => {
  it('names the error and caps the sizes the API accepts', () => {
    const e = new TypeError('x'.repeat(3000))
    const r = errorReport(e, 'at Review', '#/review/1')
    expect(r.level).toBe('ERROR')
    expect(r.message.startsWith('TypeError: xxx')).toBe(true)
    expect(r.message.length).toBe(2000)
    expect(r.component_stack).toBe('at Review')
    expect(r.url).toBe('#/review/1')
  })
})
