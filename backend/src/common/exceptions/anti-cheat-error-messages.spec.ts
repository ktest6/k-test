import { ANTI_CHEAT_ERROR_MESSAGES, resolveAntiCheatError } from './anti-cheat-error-messages';

describe('resolveAntiCheatError', () => {
  it('substitutes params into the English template', () => {
    expect(
      resolveAntiCheatError({
        code: 'REQUEST_FIELD_REQUIRED',
        params: { field: 'currentImage' },
        detail: '필수 요청 값이 누락되었습니다.',
      }),
    ).toBe("The required field 'currentImage' is missing.");
  });

  it('joins array params with a comma', () => {
    expect(
      resolveAntiCheatError({
        code: 'DOCUMENT_REQUIRED_FIELDS_MISSING',
        params: { fields: ['documentNumber', 'birthDate'] },
        detail: '여권에서 필수 정보를 읽을 수 없습니다: {fields}',
      }),
    ).toBe(
      'Could not read the following required fields from the document: documentNumber, birthDate.',
    );
  });

  it('falls back to the Korean detail for a code not in the catalog', () => {
    expect(
      resolveAntiCheatError({
        code: 'SOME_FUTURE_CODE_NOT_YET_MAPPED',
        detail: '아직 매핑되지 않은 코드의 한국어 메시지.',
      }),
    ).toBe('아직 매핑되지 않은 코드의 한국어 메시지.');
  });

  it('resolves a code with no params', () => {
    expect(
      resolveAntiCheatError({
        code: 'MONITORING_INTERNAL_ERROR',
        detail: '시험 모니터링 처리 중 오류가 발생했습니다.',
      }),
    ).toBe('An error occurred while processing exam monitoring.');
  });

  it('has an English entry for every code the catalog claims to cover (spot check count)', () => {
    expect(Object.keys(ANTI_CHEAT_ERROR_MESSAGES).length).toBe(48);
  });
});
