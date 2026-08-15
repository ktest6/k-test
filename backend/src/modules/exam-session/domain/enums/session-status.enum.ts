/** DB의 session_status enum과 값이 동일해야 한다. */
export enum SessionStatus {
  INPROGRESS = 'INPROGRESS',
  SUBMITTED = 'SUBMITTED',
  EXPIRED = 'EXPIRED',
  /** 재개(재시작) 시도를 반복해 남용 한도를 넘겨 더 이상 진행할 수 없게 된 상태. */
  BLOCKED = 'BLOCKED',
}
