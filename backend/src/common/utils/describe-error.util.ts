import axios from 'axios';

/** 로그용 에러 요약 — axios 에러면 상태코드/응답 바디까지, 아니면 message만. */
export function describeError(err: unknown): string {
  if (axios.isAxiosError(err)) {
    const status = err.response?.status ?? '(no response)';
    const body = err.response?.data ? JSON.stringify(err.response.data) : err.message;
    return `HTTP ${status} — ${body}`;
  }
  return err instanceof Error ? err.message : String(err);
}
