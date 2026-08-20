import { ApiProperty } from '@nestjs/swagger';
import { IsIn } from 'class-validator';

export const ALLOWED_CLIP_CONTENT_TYPES = ['video/webm', 'video/mp4', 'video/quicktime'] as const;

export class RequestClipUploadUrlDto {
  @ApiProperty({
    enum: ALLOWED_CLIP_CONTENT_TYPES,
    description: '영상 클립 파일 형식 (webm/mp4/mov)',
  })
  @IsIn(ALLOWED_CLIP_CONTENT_TYPES)
  contentType: string;
}
