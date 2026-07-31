import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { StorageUploadUrlService } from '../../../../infrastructure/supabase/storage-upload-url.service';
import { IdCardFileType } from '../../domain/enums/id-card-file-type.enum';
import { RequestIdCardUploadUrlDto } from '../dto/request-id-card-upload-url.dto';
import { UploadUrlResponseDto } from '../dto/upload-url-response.dto';
import { ExamAccessService } from './exam-access.service';

const STORAGE_BUCKET = 'identity-docs';

const EXTENSION_BY_CONTENT_TYPE: Record<string, string> = {
  'image/jpeg': 'jpg',
  'image/png': 'png',
  'application/pdf': 'pdf',
};

const ALLOWED_CONTENT_TYPES_BY_FILE_TYPE: Record<IdCardFileType, string[]> = {
  [IdCardFileType.ID_CARD]: ['image/jpeg', 'image/png', 'application/pdf'],
  [IdCardFileType.FACE]: ['image/jpeg', 'image/png'],
};

const FILE_NAME_BY_FILE_TYPE: Record<IdCardFileType, string> = {
  [IdCardFileType.ID_CARD]: 'id-card',
  [IdCardFileType.FACE]: 'face',
};

/**
 * id-card 인증 전용 규칙(소유권, 허용 파일 형식, 경로 이름)만 여기서 정하고,
 * 실제 signed URL 발급은 공용 StorageUploadUrlService에 위임한다 — 나중에
 * 영상/음성 업로드가 생기면 이 파일과 같은 모양으로 자기만의 규칙을 가진
 * 서비스를 하나 더 만들고 StorageUploadUrlService를 그대로 재사용하면 된다.
 * 경로는 프론트가 정하는 게 아니라 여기서 서버가 정한다 — 그래야 다른 사용자
 * 폴더로의 바꿔치기가 발급 단계부터 원천 차단된다.
 */
@Injectable()
export class IdCardUploadUrlService {
  constructor(
    private readonly storageUploadUrlService: StorageUploadUrlService,
    private readonly examAccessService: ExamAccessService,
  ) {}

  async createUploadUrl(
    userId: string,
    dto: RequestIdCardUploadUrlDto,
  ): Promise<UploadUrlResponseDto> {
    await this.examAccessService.assertApplied(userId, dto.examId);

    if (!ALLOWED_CONTENT_TYPES_BY_FILE_TYPE[dto.fileType].includes(dto.contentType)) {
      throw new ConflictDomainException(
        `${dto.fileType} 파일에는 ${dto.contentType} 형식을 사용할 수 없습니다.`,
      );
    }

    const extension = EXTENSION_BY_CONTENT_TYPE[dto.contentType];
    const fileName = FILE_NAME_BY_FILE_TYPE[dto.fileType];
    const path = `${userId}/${dto.examId}/${fileName}.${extension}`;

    return this.storageUploadUrlService.createSignedUploadUrl(STORAGE_BUCKET, path);
  }
}
