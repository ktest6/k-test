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

  @ApiProperty()
  examId: string;

  @ApiProperty({ enum: SessionStatus })
  status: SessionStatus;

  @ApiProperty()
  startedAt: Date;
}
