import { substituteTemplate } from './substitute-template.util';

describe('substituteTemplate', () => {
  it('substitutes string/number/boolean params', () => {
    expect(substituteTemplate('{a} {b} {c}', { a: 'x', b: 1, c: true })).toBe('x 1 true');
  });

  it('joins array params with a comma', () => {
    expect(substituteTemplate('fields: {fields}', { fields: ['a', 'b', 'c'] })).toBe(
      'fields: a, b, c',
    );
  });

  it('leaves the placeholder untouched when the param is missing', () => {
    expect(substituteTemplate('{missing}', {})).toBe('{missing}');
  });

  it('leaves the placeholder untouched for an unsupported value type', () => {
    expect(substituteTemplate('{obj}', { obj: { nested: true } })).toBe('{obj}');
  });

  it('uses resolveValue when it returns a string, bypassing the default handling', () => {
    const resolveValue = jest.fn().mockReturnValue('resolved');
    expect(substituteTemplate('{x}', { x: { some: 'shape' } }, resolveValue)).toBe('resolved');
    expect(resolveValue).toHaveBeenCalledWith({ some: 'shape' }, 'x');
  });

  it('falls back to default handling when resolveValue returns undefined', () => {
    const resolveValue = jest.fn().mockReturnValue(undefined);
    expect(substituteTemplate('{x}', { x: 'plain' }, resolveValue)).toBe('plain');
  });
});
