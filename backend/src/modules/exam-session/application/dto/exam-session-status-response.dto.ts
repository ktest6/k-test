import { ApiProperty } from '@nestjs/swagger';
import { SessionStatus } from '../../domain/enums/session-status.enum';

export class ExamSessionStatusResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty({
    enum: SessionStatus,
    description:
      'INPROGRESS가 아니면(SUBMITTED/EXPIRED/BLOCKED/DISQUALIFIED) 더 이상 진행할 수 없다는 뜻이다.',
  })
  status: SessionStatus;

  @ApiProperty({
    description:
      '본인인증/이어폰 확인이 다 끝나서 문항 조회·답안 제출이 가능한 상태인지. false면 검증 화면 ' +
      '(신분증 확인 → 이어폰 확인)을 먼저 보여줘야 한다 — 문항 목록은 이 값이 false인 동안 ' +
      '아직 볼 수 없다.',
  })
  verified: boolean;
}
