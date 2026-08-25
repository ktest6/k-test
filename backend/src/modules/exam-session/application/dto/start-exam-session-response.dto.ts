import { ApiProperty } from '@nestjs/swagger';
import { SessionStatus } from '../../domain/enums/session-status.enum';

export class StartExamSessionResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty({
    description:
      'id와 동일한 값. 이후 API 호출에서 쓰는 세션 식별자임을 명확히 하기 위해 같이 내려준다.',
  })
  examSessionId: string;

  @ApiProperty({ enum: SessionStatus })
  status: SessionStatus;

  @ApiProperty()
  startedAt: Date;

  @ApiProperty({
    description:
      '본인인증/이어폰 확인이 다 끝나서 문항 조회·답안 제출이 가능한 상태인지. false면 검증 화면 ' +
      '(신분증 확인 → 이어폰 확인)을 먼저 보여줘야 한다 — 문항 목록은 이 값이 false인 동안 ' +
      '아직 볼 수 없다.',
  })
  verified: boolean;
}
