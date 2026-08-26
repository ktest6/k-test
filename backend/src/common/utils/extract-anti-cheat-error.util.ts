import axios from 'axios';
import { AntiCheatError } from '../exceptions/anti-cheat-error-messages';

/**
 * anti-cheat 서비스 호출이 실패했을 때, 그 에러가 anti-cheat의 구조화된
 * `{detail, code, params?}` 응답 바디를 담고 있으면 꺼내 온다. 네트워크 자체가
 * 끊겼거나(타임아웃 등) 응답 바디가 그 형태가 아니면 null — 호출부가 기존
 * 일반 실패 메시지로 폴백해야 한다는 뜻이다.
 */
export function extractAntiCheatError(err: unknown): AntiCheatError | null {
  if (!axios.isAxiosError(err)) {
    return null;
  }

  const data: unknown = err.response?.data;
  if (
    typeof data !== 'object' ||
    data === null ||
    typeof (data as { detail?: unknown }).detail !== 'string' ||
    typeof (data as { code?: unknown }).code !== 'string'
  ) {
    return null;
  }

  const { detail, code, params } = data as { detail: string; code: string; params?: unknown };
  return {
    detail,
    code,
    params:
      typeof params === 'object' && params !== null
        ? (params as Record<string, unknown>)
        : undefined,
  };
}
