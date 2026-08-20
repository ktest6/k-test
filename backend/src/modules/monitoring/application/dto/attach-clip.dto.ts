import { ApiProperty } from '@nestjs/swagger';
import { IsString, MinLength } from 'class-validator';

export class AttachClipDto {
  @ApiProperty({
    description: '클립 업로드 URL 발급 때 받은 path를 그대로 전달',
    example: '9/100/7.webm',
  })
  @IsString()
  @MinLength(1)
  clipPath: string;
}
