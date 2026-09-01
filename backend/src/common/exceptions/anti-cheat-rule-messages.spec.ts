import { resolveAntiCheatRuleMessage } from './anti-cheat-rule-messages';

describe('resolveAntiCheatRuleMessage', () => {
  it('translates a known ruleId to English', () => {
    expect(
      resolveAntiCheatRuleMessage('RULE_PHONE_DETECTED', '시험 화면에서 휴대폰이 탐지되었습니다.'),
    ).toBe('A phone was detected on the exam screen.');
  });

  it('falls back to the Korean message for an unknown ruleId', () => {
    expect(
      resolveAntiCheatRuleMessage('RULE_SOME_FUTURE_RULE', '아직 매핑 안 된 룰의 메시지.'),
    ).toBe('아직 매핑 안 된 룰의 메시지.');
  });

  it('falls back to the Korean message when ruleId is missing', () => {
    expect(resolveAntiCheatRuleMessage(undefined, '한국어 메시지.')).toBe('한국어 메시지.');
  });
});
