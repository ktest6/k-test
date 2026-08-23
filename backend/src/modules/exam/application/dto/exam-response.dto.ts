import { ApiProperty } from '@nestjs/swagger';

export class ExamResponseDto {
  @ApiProperty()
  id: string;

  @ApiProperty()
  roundName: string;

  @ApiProperty({ description: '회차 생성 시각' })
  createdAt: Date;
}
