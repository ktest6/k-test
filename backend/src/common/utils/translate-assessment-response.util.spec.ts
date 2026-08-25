import { translateAssessmentResponse } from './translate-assessment-response.util';

describe('translateAssessmentResponse', () => {
  it('replaces top-level warnings with the English text resolved from notices', () => {
    const raw = {
      warnings: ['[채점 무효] 답안의 한글 비율이 12%로 …'],
      notices: [
        {
          code: 'VALIDITY_HANGUL_RATIO',
          params: { ratio: '12%', threshold: '50%' },
          message: '답안의 한글 비율이 12%로 기준(50%)에 못 미쳐 …',
        },
      ],
    };

    const result = translateAssessmentResponse(raw);

    expect(result.warnings).toEqual([
      'The Korean-script ratio of the answer is 12%, below the threshold of 50%, so it cannot be treated as a Korean answer. Scoring was voided.',
    ]);
  });

  it('translates note on subscores/features/checklist_results using their notice', () => {
    const raw = {
      subscores: [
        {
          area: 'delivery',
          note: '발음 평가 결과가 없어 채점하지 않았다.',
          notice: {
            code: 'SUBSCORE_DELIVERY_NO_PRONUNCIATION',
            message: '발음 평가 결과가 없어 채점하지 않았다.',
          },
        },
      ],
      features: [
        {
          id: 'pron_accuracy',
          note: "자질 'pron_accuracy' 를 쓸 수 없어 가중치를 다시 나눴다.",
          notice: {
            code: 'SUBSCORE_FEATURE_EXCLUDED',
            params: { featureId: 'pron_accuracy' },
            message: "자질 'pron_accuracy' 를 쓸 수 없어 가중치를 다시 나눴다.",
          },
        },
      ],
      checklist_results: [
        {
          id: 'c1',
          note: 'LLM 응답 누락',
          notice: { code: 'CHECKLIST_NOTE_NO_VERDICT', message: 'LLM 응답 누락' },
        },
      ],
    };

    const result = translateAssessmentResponse(raw);

    expect((result.subscores as { note: string }[])[0].note).toBe(
      'No pronunciation assessment result, so this area was not scored (excluded from the overall score). This happens for writing answers, or when transcription was done by a provider that cannot measure pronunciation.',
    );
    expect((result.features as { note: string }[])[0].note).toBe(
      "Feature 'pron_accuracy' is unavailable, so the weights were redistributed.",
    );
    expect((result.checklist_results as { note: string }[])[0].note).toBe('LLM response missing');
  });

  it('translates comment on nested evidence using its notice', () => {
    const raw = {
      subscores: [
        {
          area: 'content_task',
          evidence: [
            {
              comment: '답안에서 해당 내용을 확인했다.',
              notice: {
                code: 'CHECKLIST_COMMENT_MET_FALLBACK',
                message: '답안에서 해당 내용을 확인했다.',
              },
            },
          ],
        },
      ],
    };

    const result = translateAssessmentResponse(raw);

    const evidence = (result.subscores as { evidence: { comment: string }[] }[])[0].evidence;
    expect(evidence[0].comment).toBe('This content was confirmed in the answer.');
  });

  it('translates cross_mode_check.note for finalize responses', () => {
    const raw = {
      cross_mode_check: {
        comparable: true,
        note: '말하기 3급 / 쓰기 6급 로 3등급 차이가 난다.',
        notice: {
          code: 'FINALIZE_CROSS_CHECK_OK',
          params: { speaking: '4급', writing: '5급', gap: 1, threshold: 2 },
          message: '말하기 4급 / 쓰기 5급, 1등급 차이로 기준값(2등급) 안에 있다.',
        },
      },
    };

    const result = translateAssessmentResponse(raw);

    expect((result.cross_mode_check as { note: string }).note).toBe(
      'Speaking 4급 / writing 5급, a gap of 1 grade(s), within the threshold of 2 grade(s).',
    );
  });

  it('leaves fields untouched when there is no notice to translate from', () => {
    const raw = { warnings: ['한국어 그대로'], subscores: [{ note: '한국어 그대로' }] };

    const result = translateAssessmentResponse(raw);

    expect(result.warnings).toEqual(['한국어 그대로']);
    expect((result.subscores as { note: string }[])[0].note).toBe('한국어 그대로');
  });

  it('does not mutate the original object', () => {
    const raw = {
      warnings: ['[채점 무효] …'],
      notices: [{ code: 'CHECKLIST_MET', message: '충족' }],
    };

    translateAssessmentResponse(raw);

    expect(raw.warnings).toEqual(['[채점 무효] …']);
  });
});
