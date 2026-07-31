import { ApiProperty } from '@nestjs/swagger';
import { ChecklistItemResponseDto } from './checklist-item-response.dto';

export class GeneratedQuestionResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty({ description: '문항 세부 유형 (work_log, messenger_report 등)' })
  part: string;

  @ApiProperty({
    description: '문항 원문 지문 — 항목 ID, 프롬프트, 기대 문체, 참고 키워드를 담고 있다',
  })
  content: Record<string, unknown>;

  @ApiProperty({ type: [ChecklistItemResponseDto] })
  checklistItems: ChecklistItemResponseDto[];
}
