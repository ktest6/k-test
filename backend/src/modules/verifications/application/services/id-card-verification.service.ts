import { Inject, Injectable } from '@nestjs/common';
import {
  ConflictDomainException,
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import {
  IDENTITY_PROVIDER,
  IdentityImageInput,
  IdentityProviderPort,
  VerifyIdentityInput,
  VerifyIdentityResult,
} from '../../../ai/domain/ports/identity-provider.port';
import { IdentityDocumentType } from '../../../user/domain/enums/identity-document-type.enum';
import { UserService } from '../../../user/application/services/user.service';
import { VerifyIdCardDto } from '../dto/verify-id-card.dto';
import { VerifyIdCardResponseDto } from '../dto/verify-id-card-response.dto';
import { ExamAccessService } from './exam-access.service';

const IDENTITY_DOCS_BUCKET = 'identity-docs';

const DOCUMENT_TYPE_INPUT_BY_USER_ID_TYPE: Record<
  IdentityDocumentType,
  VerifyIdentityInput['documentType']
> = {
  [IdentityDocumentType.PASSPORT]: 'PASSPORT',
  [IdentityDocumentType.ARC]: 'ARC',
};

/**
 * 시험 시작 전 본인인증(신분증-얼굴 대조). 이미지 자체는 프론트가
 * POST /verifications/id-card/upload-url로 발급받은 signed URL로 Supabase
 * Storage에 직접 올리고, 여기서는 그 경로만 받아 소유권을 검증한다.
 *
 * 실제 대조는 FastAPI 서비스(IdentityProviderPort)에 위임한다. scoring/
 * monitoring과 달리 여기서는 외부 서비스 실패를 "이상 없음"으로 눙치지
 * 않는다 — 본인인증은 보안 게이트라, 실패를 성공으로 처리하면 인증을
 * 우회하는 셈이 된다. 통신 실패 시 그대로 에러를 던져 재시도를 유도한다.
 */
@Injectable()
export class IdCardVerificationService {
  constructor(
    private readonly supabaseService: SupabaseService,
    private readonly examAccessService: ExamAccessService,
    private readonly userService: UserService,
    @Inject(IDENTITY_PROVIDER) private readonly identityProvider: IdentityProviderPort,
  ) {}

  async verify(userId: string, dto: VerifyIdCardDto): Promise<VerifyIdCardResponseDto> {
    const client = this.supabaseService.getAdminClient();

    // 1) 전달받은 경로가 실제로 이 사용자 소유 폴더 아래인지 확인.
    // upload-url 발급 단계에서 이미 서버가 경로를 정해줬으므로(바꿔치기 불가),
    // 여기서는 그 경로가 그대로 전달됐는지 한 번 더 확인하는 방어 계층이다.
    const expectedPrefix = `${userId}/${dto.examId}/`;
    if (!dto.idCardPath.startsWith(expectedPrefix) || !dto.facePath.startsWith(expectedPrefix)) {
      throw new ForbiddenDomainException('본인 파일 경로가 아닙니다.');
    }

    // 2) 신청한 회차인지 확인
    await this.examAccessService.assertApplied(userId, dto.examId);

    // 3) FastAPI로 얼굴 대조 요청 — first_name/last_name/birth_date/documentType은
    // 프론트가 아니라 가입 시 등록된 정보를 그대로 쓴다(신청 정보와의 대조가 목적이므로).
    const user = await this.userService.findById(userId);
    const [idCardImage, faceImage] = await Promise.all([
      this.downloadImage(client, dto.idCardPath),
      this.downloadImage(client, dto.facePath),
    ]);

    let result: VerifyIdentityResult;
    try {
      result = await this.identityProvider.verify({
        examId: dto.examId,
        examineeId: userId,
        capturedAt: dto.capturedAt,
        sourceImage: idCardImage,
        targetImage: faceImage,
        firstName: user.firstName,
        lastName: user.lastName,
        birthDate: user.birthDate,
        documentType: DOCUMENT_TYPE_INPUT_BY_USER_ID_TYPE[user.idType],
      });
    } catch {
      throw new ConflictDomainException(
        '본인인증 서비스와 통신에 실패했습니다. 잠시 후 다시 시도해주세요.',
      );
    }

    const matched = result.verified;
    // similarity(0~100)를 identity_logs.confidence(0~1) 스케일에 맞춘다.
    const confidence = result.similarity / 100;

    // 4) 결과 로그 저장
    await client.from('identity_logs').insert({
      exam_id: Number(dto.examId),
      user_id: Number(userId),
      id_card_path: dto.idCardPath,
      face_path: dto.facePath,
      matched,
      confidence,
      document_type: result.documentType,
      raw_response: result.raw,
      verified_at: new Date().toISOString(),
    });

    return {
      matched,
      confidence,
      faceVerified: result.faceVerified,
      similarity: result.similarity,
      threshold: result.threshold,
      matchedFaceCount: result.matchedFaceCount,
      unmatchedFaceCount: result.unmatchedFaceCount,
      applicantVerified: result.applicantVerified,
      documentType: result.documentType,
      fieldMatches: result.fieldMatches,
      message: result.message,
    };
  }

  /** 시험 시작 전 게이트 체크(ExamSessionService.start)에서 쓰는 완료 여부 조회. */
  async hasVerifiedExam(examId: string, userId: string): Promise<boolean> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from('identity_logs')
      .select('id')
      .eq('exam_id', Number(examId))
      .eq('user_id', Number(userId))
      .eq('matched', true)
      .limit(1)
      .maybeSingle();

    return data !== null;
  }

  /** 모니터링(부정행위 감지)에서 동일인 검사용 기준 얼굴 이미지 경로가 필요할 때 쓴다. */
  async getVerifiedFacePath(examId: string, userId: string): Promise<string | null> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from('identity_logs')
      .select('face_path')
      .eq('exam_id', Number(examId))
      .eq('user_id', Number(userId))
      .eq('matched', true)
      .order('verified_at', { ascending: false })
      .limit(1)
      .maybeSingle<{ face_path: string }>();

    return data?.face_path ?? null;
  }

  private async downloadImage(
    client: ReturnType<SupabaseService['getAdminClient']>,
    path: string,
  ): Promise<IdentityImageInput> {
    const { data, error } = await client.storage.from(IDENTITY_DOCS_BUCKET).download(path);
    if (error || !data) {
      throw new NotFoundDomainException(`이미지를 찾을 수 없습니다 (path=${path}).`);
    }

    const buffer = Buffer.from(await data.arrayBuffer());
    const filename = path.split('/').pop() ?? 'image.jpg';
    return { buffer, filename, contentType: data.type || 'image/jpeg' };
  }
}
