import { ApiProperty } from '@nestjs/swagger';
import { IsIn } from 'class-validator';

export const ALLOWED_ANSWER_AUDIO_CONTENT_TYPES = [
  'audio/webm',
  'audio/wav',
  'audio/x-wav',
  'audio/mpeg',
  'audio/mp4',
  'audio/ogg',
] as const;

export class RequestAnswerAudioUploadUrlDto {
  @ApiProperty({
    enum: ALLOWED_ANSWER_AUDIO_CONTENT_TYPES,
    description: '녹음 파일 형식 (webm/wav/mp3/m4a/ogg)',
  })
  @IsIn(ALLOWED_ANSWER_AUDIO_CONTENT_TYPES)
  contentType: string;
}
