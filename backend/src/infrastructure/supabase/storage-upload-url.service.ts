import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../common/exceptions/domain.exception';
import { SupabaseService } from './supabase.service';

export interface SignedUploadUrl {
  path: string;
  signedUrl: string;
  token: string;
}

/**
 * Supabase Storage의 signed upload URL 발급만 담당하는 순수 인프라 서비스.
 * 버킷/경로 규칙, 소유권 검증, 허용 파일 형식 같은 도메인별 규칙은 이
 * 서비스가 전혀 모른다 — 호출하는 쪽(IdCardUploadUrlService, 추후 영상/음성
 * 업로드 서비스 등)이 그 규칙을 다 정한 뒤 최종 bucket/path만 여기로 넘긴다.
 * 새 파일 업로드 기능을 추가할 때 이 서비스는 그대로 재사용하면 된다.
 */
@Injectable()
export class StorageUploadUrlService {
  constructor(private readonly supabaseService: SupabaseService) {}

  async createSignedUploadUrl(bucket: string, path: string): Promise<SignedUploadUrl> {
    const client = this.supabaseService.getAdminClient();
    const { data, error } = await client.storage.from(bucket).createSignedUploadUrl(path);

    if (error || !data) {
      throw new ConflictDomainException(error?.message ?? '업로드 URL 발급에 실패했습니다.');
    }

    return { path: data.path, signedUrl: data.signedUrl, token: data.token };
  }
}
