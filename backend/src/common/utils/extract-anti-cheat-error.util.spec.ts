import { extractAntiCheatError } from './extract-anti-cheat-error.util';

function buildAxiosError(data: unknown): unknown {
  return {
    isAxiosError: true,
    message: 'Request failed',
    response: { status: 400, data },
  };
}

describe('extractAntiCheatError', () => {
  it('extracts detail/code/params from a structured anti-cheat error response', () => {
    const err = buildAxiosError({
      detail: '필수 요청 값이 누락되었습니다.',
      code: 'REQUEST_FIELD_REQUIRED',
      params: { field: 'currentImage' },
    });

    expect(extractAntiCheatError(err)).toEqual({
      detail: '필수 요청 값이 누락되었습니다.',
      code: 'REQUEST_FIELD_REQUIRED',
      params: { field: 'currentImage' },
    });
  });

  it('extracts detail/code with params undefined when params is absent', () => {
    const err = buildAxiosError({
      detail: '시험 모니터링 처리 중 오류가 발생했습니다.',
      code: 'MONITORING_INTERNAL_ERROR',
    });

    expect(extractAntiCheatError(err)).toEqual({
      detail: '시험 모니터링 처리 중 오류가 발생했습니다.',
      code: 'MONITORING_INTERNAL_ERROR',
      params: undefined,
    });
  });

  it('returns null when the error is not an axios error', () => {
    expect(extractAntiCheatError(new Error('plain error'))).toBeNull();
  });

  it('returns null when the response body does not have code/detail strings', () => {
    expect(extractAntiCheatError(buildAxiosError({ message: 'unexpected shape' }))).toBeNull();
  });

  it('returns null when there is no response at all (e.g. network timeout)', () => {
    expect(extractAntiCheatError({ isAxiosError: true, message: 'timeout' })).toBeNull();
  });
});
