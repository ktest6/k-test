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
    description:
      '아직 답안이 없는 첫 문항 ID — 매 조회 시 답안 저장 현황으로 다시 계산한다(저장된 값 아님). ' +
      '중단 후 재개 시 이 문항부터 보여주면 된다. 모든 문항에 답했거나 진행중이 아니면 null.',
  })
  nextQuestionId: string | null;

  @ApiProperty({ description: '응시 기간(회차 close_at) 기준 남은 초. 진행중이 아니면 0.' })
  remainingSeconds: number;
}
