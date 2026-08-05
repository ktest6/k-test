import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../config/configuration';

/**
 * public 버킷에 저장된 파일의 접근 가능한 URL을 만든다. Supabase Storage의
 * public URL 형태는 고정 규칙(`/storage/v1/object/public/{bucket}/{path}`)이라
 * 실제 API 호출 없이 문자열 조합만으로 계산 가능하다. private 버킷(예:
 * identity-docs)에는 쓰면 안 된다 — 그건 signed URL이 따로 필요하다.
 */
@Injectable()
export class StoragePublicUrlService {
  constructor(@Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>) {}

  toPublicUrl(bucket: string, path: string): string {
    return `${this.config.supabase.url}/storage/v1/object/public/${bucket}/${path}`;
  }
}
