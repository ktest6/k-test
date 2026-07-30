import { ApiProperty } from '@nestjs/swagger';

export class DeleteQuestionResponseDto {
  @ApiProperty()
  id: string;
}
