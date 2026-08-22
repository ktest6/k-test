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
    description:
      '시험을 아직 시작한 적 없으면 null(마감 1시간 전 시작 데드라인이 지나 EXPIRED여도 null).',
  })
  examSessionId: string | null;

  @ApiPropertyOptional({
    enum: SessionStatus,
    nullable: true,
    description:
      '시험을 아직 시작한 적 없고 마감 1시간 전 시작 데드라인도 지났으면 EXPIRED, 그 전이면 null. ' +
      'examSessionId는 참고용 값이며, [이어서 풀기]는 이 값을 쓰지 않고 항상 ' +
      'POST /exams/:id/sessions를 다시 호출해야 한다(재개 남용 방지 카운트가 그 호출로만 세어짐).',
  })
  sessionStatus: SessionStatus | null;

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description: '시험을 제출(완료)한 시각. 아직 제출 전이면 null.',
  })
  submittedAt: Date | null;

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description:
      '최종 리포트(/finalize) id. 아직 채점 결과가 없으면(진행중이거나 재시도 대기중) null.',
  })
  examResultId: string | null;

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description:
      '최종 등급(A~F). examResultId는 있는데 이 값이 F면 assessment가 채점 커버리지 부족으로 ' +
      '등급을 확정하지 못한 경우일 수 있다(예: 스킵을 너무 많이 한 경우) — 완주하지 못한 것으로 ' +
      '간주해 F로 확정한다.',
  })
  finalGrade: string | null;
}
