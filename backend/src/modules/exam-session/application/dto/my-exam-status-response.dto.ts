import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { ExamStatus } from '../../../exam/domain/enums/exam-status.enum';
import { SessionStatus } from '../../domain/enums/session-status.enum';

/** 마이페이지 "내 시험 현황" 한 줄 — 신청한 회차 하나에 대응된다. */
export class MyExamStatusResponseDto {
  @ApiProperty()
  examId: string;

  @ApiProperty()
  roundName: string;

  @ApiProperty({ description: '시험 응시 시작 시각' })
  openAt: Date;

  @ApiProperty({ description: '시험 응시 마감 시각' })
  closeAt: Date;

  @ApiProperty({ enum: ExamStatus, description: '회차 자체의 시간 기준 상태(신청과 무관)' })
  examStatus: ExamStatus;

  @ApiProperty()
  appliedAt: Date;

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description: '시험을 아직 시작한 적 없으면 null.',
  })
  examSessionId: string | null;

  @ApiPropertyOptional({
    enum: SessionStatus,
    nullable: true,
    description:
      '시험을 아직 시작한 적 없으면 null. 참고용 값이며, [이어서 풀기]는 이 값을 쓰지 않고 ' +
      '항상 POST /exams/:id/sessions를 다시 호출해야 한다(재개 남용 방지 카운트가 그 호출로만 세어짐).',
  })
  sessionStatus: SessionStatus | null;
}
