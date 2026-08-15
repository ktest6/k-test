import { ApiProperty } from '@nestjs/swagger';
import { SessionStatus } from '../../domain/enums/session-status.enum';

export class ExamSessionStatusResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  examId: string;

  @ApiProperty({
    enum: SessionStatus,
    description:
      'INPROGRESS 상태에서 응시 기간이 지나면 저장된 값과 무관하게 EXPIRED로 계산되어 내려온다. ' +
      'INPROGRESS가 아니면(SUBMITTED/EXPIRED/BLOCKED) 더 이상 진행할 수 없다는 뜻이다.',
  })
  status: SessionStatus;
}
