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
      'INPROGRESS 상태에서 응시 기간이 지나면 저장된 값과 무관하게 EXPIRED로 계산되어 내려온다.',
  })
  status: SessionStatus;

  @ApiProperty({
    type: String,
    nullable: true,
    description: '마지막으로 진입한 문항 ID — 중단 후 재개 시 이 문항부터 다시 보여주면 된다.',
  })
  currentQuestionId: string | null;

  @ApiProperty({ description: '응시 기간(회차 close_at) 기준 남은 초. 진행중이 아니면 0.' })
  remainingSeconds: number;
}
