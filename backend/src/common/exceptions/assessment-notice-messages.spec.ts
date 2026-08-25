import { NOTICE_MESSAGES, Notice, resolveNotice } from './assessment-notice-messages';

describe('resolveNotice', () => {
  it('substitutes simple params into the English template', () => {
    const notice: Notice = {
      code: 'AUDIO_FILE_TOO_LARGE',
      params: { actualMb: 25.3, maxMb: 20 },
      message: '음성 파일이 25.3MB로 너무 크다(최대 20MB).',
    };

    expect(resolveNotice(notice)).toBe(
      'The audio file is 25.3MB, which is too large (maximum 20MB).',
    );
  });

  it('falls back to the Korean message for a code not in the catalog', () => {
    const notice: Notice = {
      code: 'SOME_FUTURE_CODE_NOT_YET_MAPPED',
      message: '아직 매핑되지 않은 코드의 한국어 메시지.',
    };

    expect(resolveNotice(notice)).toBe('아직 매핑되지 않은 코드의 한국어 메시지.');
  });

  it('recursively resolves a nested notice passed as a params value', () => {
    const notice: Notice = {
      code: 'VALIDITY_INVALID_WRAP',
      params: {
        reason: '답안의 한글 비율이 12%로 기준(50%)에 못 미쳐 …',
        reasonNotice: {
          code: 'VALIDITY_HANGUL_RATIO',
          params: { ratio: '12%', threshold: '50%' },
          message:
            '답안의 한글 비율이 12%로 기준(50%)에 못 미쳐 한국어 답안으로 볼 수 없다. 채점을 무효로 처리했다.',
        },
      },
      message: '[채점 무효] 답안의 한글 비율이 12%로 기준(50%)에 못 미쳐 …',
    };

    // {reason}이 아니라 {reasonNotice}를 참조하는 코드로 재구성해서 중첩 해석을 검증한다.
    const wrapUsingNestedNotice: Notice = { ...notice, code: 'VALIDITY_NOT_SCORED_NOTE' };
    const result = resolveNotice({
      ...wrapUsingNestedNotice,
      params: { reason: notice.params!.reasonNotice },
    });

    expect(result).toBe(
      'Not scored because the answer failed a validity guard: The Korean-script ratio of the answer is 12%, below the threshold of 50%, so it cannot be treated as a Korean answer. Scoring was voided.',
    );
  });

  it('passes LLM_FREE_TEXT through verbatim via the {text} placeholder', () => {
    const notice: Notice = {
      code: 'LLM_FREE_TEXT',
      params: { text: 'The answer explained the reason for being late.' },
      message: '답안에서 지각한 이유를 밝혔다.',
    };

    expect(resolveNotice(notice)).toBe('The answer explained the reason for being late.');
  });

  it('leaves a placeholder untouched when its param is missing', () => {
    const notice: Notice = {
      code: 'AUDIO_FILE_TOO_LARGE',
      params: { actualMb: 25.3 },
      message: '음성 파일이 25.3MB로 너무 크다.',
    };

    expect(resolveNotice(notice)).toBe(
      'The audio file is 25.3MB, which is too large (maximum {maxMb}MB).',
    );
  });

  it('has an English entry for every code the catalog claims to cover (spot check count)', () => {
    expect(Object.keys(NOTICE_MESSAGES).length).toBe(189);
  });
});
