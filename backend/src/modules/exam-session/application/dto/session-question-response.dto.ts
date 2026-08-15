import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';
import { QuestionSectionType } from '../../../question/domain/enums/question-section-type.enum';

/**
 * 응시자에게 보여줄 문항 — 관리자용(AssignedQuestionResponseDto)과 달리
 * checklist/weight는 절대 안 담는다. 채점 기준이 그대로 노출되면 답을
 * 그거에 맞춰 꾸며 쓸 수 있기 때문.
 */
export class SessionQuestionResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty({ enum: QuestionSectionType, description: '문항 유형' })
  part: QuestionSectionType;

  @ApiProperty({ description: '이 세션에서 이미 답안을 저장했는지 여부' })
  answered: boolean;

  @ApiProperty({ description: '준비시간(초)' })
  preparationSeconds: number;

  @ApiProperty({ description: '응답시간(초)' })
  responseSeconds: number;

  @ApiProperty({
    type: [String],
    description:
      '유형별 고정 안내문구. SITUATION_DESCRIPTION/READ_AND_EXPLAIN은 1개, ANSWER_QUESTION은 2개(지시문+안내문구)',
  })
  guideTexts: string[];

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description: '지시문 — SITUATION_DESCRIPTION/READ_AND_EXPLAIN 문항만 값 있음',
  })
  instruction: string | null;

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description: '상황 묘사 이미지 URL(Supabase public URL) — SITUATION_DESCRIPTION 문항만 값 있음',
  })
  imageUrl: string | null;

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description: '안전수칙 타이틀 — READ_AND_EXPLAIN 문항만 값 있음',
  })
  safetyRulesTitle: string | null;

  @ApiPropertyOptional({
    type: [String],
    nullable: true,
    description: '안전수칙 항목 리스트 — READ_AND_EXPLAIN 문항만 값 있음',
  })
  safetyRules: string[] | null;

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description: '질문 음성 파일 URL(Supabase public URL) — ANSWER_QUESTION 문항만 값 있음',
  })
  audioUrl: string | null;
}
