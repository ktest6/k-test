import { ApiProperty } from '@nestjs/swagger';
import { SessionStatus } from '../../../exam-session/domain/enums/session-status.enum';

export class QuickStartResponseDto {
  @ApiProperty({ description: '새로 만들어진 테스트 계정의 액세스 토큰 — 이후 요청에 그대로 사용' })
  accessToken: string;

  @ApiProperty()
  userId: string;

  @ApiProperty({ description: '테스트용으로 자동 생성된 이메일(실제 수신 불가)' })
  email: string;

  @ApiProperty({ description: '바로 문항 조회·답안 제출이 가능한 상태의 세션 id' })
  examSessionId: string;

  @ApiProperty({ enum: SessionStatus })
  status: SessionStatus;

  @ApiProperty({
    description:
      '항상 true — 본인인증/이어폰체크를 실제로 통과한 것과 동일한 기록을 미리 만들어둔다.',
  })
  verified: boolean;
}
