import { describe, expect, it } from 'vitest'
import { epicLane as lane } from '../test/fixtures'
import { lanesNeedingYou } from './lanes'

describe('lanesNeedingYou', () => {
  it('só escalada e falha esperam você', () => {
    const lanes = [lane('E1', 'escalated'), lane('E2', 'failed'), lane('E3', 'limited')]
    expect(lanesNeedingYou(lanes).map((l) => l.id)).toEqual(['E1', 'E2'])
  })
})
