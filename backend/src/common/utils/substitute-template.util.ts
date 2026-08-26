/**
 * "{key}" 자리표시자를 params[key]로 치환하는 공용 템플릿 치환기. 외부 서비스
 * (assessment/anti-cheat)가 각자 code+params 조합으로 상태를 알려주고, 우리
 * 쪽에서 그 code를 영어 문장 템플릿으로 미리 매핑해두는 동일한 패턴을 쓰길래
 * 치환 로직만 공용으로 뺐다. 도메인마다 다른 처리(예: assessment의 중첩 notice
 * 재귀 해석)는 resolveValue 콜백으로 넘겨받는다.
 */
export function substituteTemplate(
  template: string,
  params: Record<string, unknown>,
  resolveValue?: (value: unknown, key: string) => string | undefined,
): string {
  return template.replace(/\{(\w+)\}/g, (match, key: string) => {
    const value = params[key];
    const resolved = resolveValue?.(value, key);
    if (resolved !== undefined) {
      return resolved;
    }
    if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
      return String(value);
    }
    if (Array.isArray(value)) {
      return value.map(String).join(', ');
    }
    // 값이 없거나(템플릿이 안 쓰는 부가 필드) 처리할 수 없는 타입이면 원래 {key} 표기를 그대로 남긴다.
    return match;
  });
}
