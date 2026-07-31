import { MockQuestionGeneratorAdapter } from './mock-question-generator.adapter';

describe('MockQuestionGeneratorAdapter', () => {
  it('returns the fixed writing_v0 set mapped to camelCase, ignoring the input', async () => {
    const adapter = new MockQuestionGeneratorAdapter();

    const result = await adapter.generate();

    expect(result.version).toBe('writing_v0');
    expect(result.mode).toBe('writing');
    expect(result.items).toHaveLength(5);
    expect(result.items[0]).toMatchObject({
      itemId: 'WRT-001',
      itemType: 'work_log',
      expectedRegister: 'formal',
    });
    expect(result.items[0].referenceKeywords).toEqual(['작업', '문제', '처리', '해결']);
    expect(result.items[1].checklist).toHaveLength(4);
  });
});
