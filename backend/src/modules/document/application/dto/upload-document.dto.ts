import { ApiPropertyOptional, ApiProperty } from '@nestjs/swagger';
import { IsInt, IsOptional, IsString, MinLength } from 'class-validator';

export class UploadDocumentDto {
  @ApiProperty({
    description: '프론트가 Supabase Storage에 직접 업로드한 파일 경로',
    example: 'documents/2026/writing-source.pdf',
  })
  @IsString()
  @MinLength(1)
  filePath: string;

  @ApiPropertyOptional({ description: '생략하면 filePath의 마지막 경로 조각을 사용한다' })
  @IsOptional()
  @IsString()
  fileName?: string;

  @ApiPropertyOptional({
    description:
      '업로드 시점에 이미 회차를 알고 있으면 미리 지정. 생성되는 문항의 exam_id는 이 값과 무관하게 항상 NULL이며(회차 배정은 별도 기능), 여기 넘긴 값은 문서 메타데이터에만 보관된다.',
  })
  @IsOptional()
  @IsInt()
  examId?: number;
}
