import { ApiProperty } from '@nestjs/swagger';

export class UploadUrlResponseDto {
  @ApiProperty({
    description: 'Storage 상 저장될 경로 — 업로드 후 이 값을 그대로 verify API에 전달',
    example: '1/1/id-card.jpg',
  })
  path: string;

  @ApiProperty({ description: '이 URL로 파일을 업로드하면 됨 (짧은 시간 내 만료)' })
  signedUrl: string;

  @ApiProperty({ description: 'Supabase SDK의 uploadToSignedUrl 호출 시 필요한 토큰' })
  token: string;
}
