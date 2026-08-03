import { ApiProperty, ApiPropertyOptional } from '@nestjs/swagger';

/**
 * 응시자에게 보여줄 문항 — 관리자용(AssignedQuestionResponseDto)과 달리
 * checklist/weight/expected_register/reference_keywords는 절대 안 담는다.
 * 채점 기준이 그대로 노출되면 답을 그거에 맞춰 꾸며 쓸 수 있기 때문.
 */
export class SessionQuestionResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty({
    description: '문항 세부 유형 (work_log, messenger_report, picture_description 등)',
  })
  part: string;

  @ApiProperty({ description: '문항 지문' })
  prompt: string;

  @ApiPropertyOptional({
    type: String,
    nullable: true,
    description: '그림 묘사 등 이미지가 있는 문항의 이미지 경로. 없으면 null',
  })
  imageUrl: string | null;
}
