import { Inject, Injectable, Logger } from '@nestjs/common';
import {
  ConflictDomainException,
  ForbiddenDomainException,
  NotFoundDomainException,
} from '../../../../common/exceptions/domain.exception';
import { describeError } from '../../../../common/utils/describe-error.util';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import {
  IDENTITY_PROVIDER,
  IdentityImageInput,
  IdentityProviderPort,
  VerifyIdentityInput,
  VerifyIdentityResult,
} from '../../../ai/domain/ports/identity-provider.port';
import { UserService } from '../../../user/application/services/user.service';
import { VerifyIdCardDto } from '../dto/verify-id-card.dto';
import { VerifyIdCardResponseDto } from '../dto/verify-id-card-response.dto';
import { ExamAccessService } from './exam-access.service';

const IDENTITY_DOCS_BUCKET = 'identity-docs';

/**
 * 시험 시작 전 본인인증(신분증-얼굴 대조). 이미지 자체는 프론트가
 * POST /verifications/id-card/upload-url로 발급받은 signed URL로 Supabase
 * Storage에 직접 올리고, 여기서는 그 경로만 받아 소유권을 검증한다.
 *
 * 실제 대조는 FastAPI 서비스(IdentityProviderPort)에 위임한다. scoring/
 * monitoring과 달리 여기서는 외부 서비스 실패를 "이상 없음"으로 눙치지
 * 않는다 — 본인인증은 보안 게이트라, 실패를 성공으로 처리하면 인증을
 * 우회하는 셈이 된다. 통신 실패 시 그대로 에러를 던져 재시도를 유도한다
 * (이때는 결과를 못 받은 것이므로 아래 이미지 삭제도 일어나지 않는다 —
 * 같은 사진으로 재시도 가능해야 한다).
 *
 * 신분증 사진은 대조 결과를 실제로 받는 즉시(일치/불일치 무관) Storage에서
 * 삭제한다 — 그 이후로는 아무도 다시 읽지 않는 가장 민감한 이미지라 최대한
 * 짧게 보관한다.
 *
 * 얼굴 사진은 대조에 성공(matched: true)했을 때만 남긴다 — 모니터링(부정행위
 * 감지)이 시험 내내 getVerifiedFacePath()로 이 사진을 동일인 검사 기준
 * 이미지로 재사용하는데, 그 조회 자체가 matched=true인 로그만 대상으로 하기
 * 때문이다. 즉 불일치로 끝난 시도의 얼굴 사진은 그 후로 아무도 읽지 않으므로
 * 신분증과 함께 정리한다. 성공한 시도의 얼굴 사진은 세션이 더 이상
 * INPROGRESS가 아니게 되는 시점에 cleanupVerifiedFaceImage()로 정리한다
 * (ExamSessionService.getStatus()에서 호출) — 채점 완료 여부와는 무관하다,
 * 얼굴 사진은 채점에 전혀 쓰이지 않기 때문이다.
 */
@Injectable()
export class IdCardVerificationService {
  private readonly logger = new Logger(IdCardVerificationService.name);

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
    if (!user.idNumber) {
      throw new ConflictDomainException(
        '먼저 여권번호를 등록해야 본인인증을 진행할 수 있습니다.',
      );
    }

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
        documentNumber: user.idNumber,
      });
    } catch (err) {
      this.logger.warn(
        `본인인증 서비스 통신 실패 (examId=${dto.examId}, userId=${userId}): ${describeError(err)}`,
      );
      throw new ConflictDomainException(
        '본인인증 서비스와 통신에 실패했습니다. 잠시 후 다시 시도해주세요.',
      );
    }

    const matched = result.verified;
    // similarity(0~100)를 identity_logs.confidence(0~1) 스케일에 맞춘다.
    const confidence = result.similarity / 100;

    // 4) 신분증 사진은 결과를 받은 이 시점부터 더 이상 쓰이지 않으므로 항상 정리한다.
    // 얼굴 사진은 대조에 성공했을 때만 남긴다(모니터링이 재사용) — 불일치로 끝났으면
    // 그 얼굴 사진도 아무도 다시 안 쓰므로 함께 정리한다. 삭제 실패는 본인인증 자체를
    // 실패시킬 이유가 아니라 경고만 남긴다.
    const pathsToDelete = matched ? [dto.idCardPath] : [dto.idCardPath, dto.facePath];
    await this.deleteImages(client, pathsToDelete);

    // 5) 결과 로그 저장
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

  /**
   * 시험 세션이 끝난(더 이상 INPROGRESS가 아닌) 뒤 더 이상 필요 없는 동일인
   * 검사 기준 얼굴 이미지를 정리한다. 이미 정리됐거나 애초에 검증 로그가
   * 없으면 조용히 아무 일도 하지 않는다(멱등) — 세션 상태를 조회할 때마다
   * 반복 호출돼도 안전하다.
   */
  async cleanupVerifiedFaceImage(examId: string, userId: string): Promise<void> {
    const facePath = await this.getVerifiedFacePath(examId, userId);
    if (!facePath) {
      return;
    }

    const client = this.supabaseService.getAdminClient();
    await this.deleteImages(client, [facePath]);
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

  private async deleteImages(
    client: ReturnType<SupabaseService['getAdminClient']>,
    paths: string[],
  ): Promise<void> {
    const { error } = await client.storage.from(IDENTITY_DOCS_BUCKET).remove(paths);
    if (error) {
      this.logger.warn(`이미지 삭제 실패 (paths=${paths.join(', ')}): ${error.message}`);
    }
  }
}
