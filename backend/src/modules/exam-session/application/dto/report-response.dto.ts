import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { QuestionSectionType } from '../../../question/domain/enums/question-section-type.enum';

export class ReportRequiredPointDto {
  @ApiProperty()
  description: string;

  @ApiProperty()
  met: boolean;
}

export class ReportTaskResponseDto {
  @ApiProperty()
  questionId: string;

  @ApiProperty({ enum: QuestionSectionType })
  part: QuestionSectionType;

  @ApiProperty({ description: '건너뛴 문항이면 true(명시적 스킵/미응답 둘 다 포함).' })
  skipped: boolean;

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description: '응시자 답변(STT 전사 텍스트). 건너뛴 문항이면 null.',
  })
  response: string | null;

  @ApiPropertyOptional({
    type: [ReportRequiredPointDto],
    nullable: true,
    description: '문항 채점 체크리스트 충족 여부. 건너뛴 문항이면 null.',
  })
  requiredPoints: ReportRequiredPointDto[] | null;
}

export class ReportDomainScoreResponseDto {
  @ApiProperty({
    description: '영역 키(예: content_task/language_use/delivery) — 표시 라벨은 프런트가 매핑.',
  })
  area: string;

  @ApiProperty({ description: '0~100 점수' })
  score: number;
}

export class ReportViolationResponseDto {
  @ApiProperty({
    description:
      '부정행위 신호 종류. 프런트 직접 감지(TAB_SWITCH/DUAL_MONITOR 등)와 AI 모니터링 감지' +
      '(EYE_GAZE_AWAY/MULTIPLE_FACES/PHONE_DETECTED 등)가 같은 필드에 섞여 온다.',
  })
  eventType: string;

  @ApiProperty({ enum: ['LOW', 'MEDIUM', 'HIGH'] })
  severity: 'LOW' | 'MEDIUM' | 'HIGH';

  @ApiProperty()
  count: number;
}

export class ReportResponseDto {
  @ApiProperty()
  examResultId: string;

  @ApiProperty()
  examSessionId: string;

  @ApiProperty()
  candidateName: string;

  @ApiProperty({ description: '응시 시작 시각' })
  startedAt: Date;

  @ApiProperty({ description: '최종 등급(A~F)' })
  finalGrade: string;

  @ApiPropertyOptional({ type: Number, nullable: true })
  percentile: number | null;

  @ApiProperty({ type: [ReportDomainScoreResponseDto] })
  domainScores: ReportDomainScoreResponseDto[];

  @ApiProperty({
    type: [ReportTaskResponseDto],
    description: '배정된 문항 순서 그대로(=응시 순서) 나열.',
  })
  tasks: ReportTaskResponseDto[];

  @ApiProperty({ type: [ReportViolationResponseDto] })
  violations: ReportViolationResponseDto[];
}
