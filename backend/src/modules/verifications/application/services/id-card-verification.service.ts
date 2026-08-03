import { HttpService } from '@nestjs/axios';
import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import { ForbiddenDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { UserService } from '../../../user/application/services/user.service';
import { VerifyIdCardDto } from '../dto/verify-id-card.dto';
import { VerifyIdCardResponseDto } from '../dto/verify-id-card-response.dto';
import { ExamAccessService } from './exam-access.service';

/**
 * 시험 시작 전 본인인증(신분증-얼굴 대조). 이미지 자체는 프론트가
 * POST /verifications/id-card/upload-url로 발급받은 signed URL로 Supabase
 * Storage에 직접 올리고, 여기서는 그 경로만 받아 소유권을 검증한다.
 *
 * FastAPI 얼굴 대조 서비스가 아직 배포되지 않아 실제 호출은 주석 처리해두고
 * 임시로 항상 matched: true를 반환한다 — 나머지 플로우(업로드, 세션/경로
 * 소유권 검증, 로그 기록)는 이 상태로도 끝까지 테스트할 수 있다. FastAPI
 * 배포되면 아래 verifyWithFastApi() 호출 부분 주석 해제할 것.
 */
@Injectable()
export class IdCardVerificationService {
  constructor(
    private readonly supabaseService: SupabaseService,
    private readonly examAccessService: ExamAccessService,
    private readonly userService: UserService,
    private readonly httpService: HttpService,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
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

    // 3) FastAPI(VM)로 얼굴 대조 요청
    // TODO: FastAPI 배포되면 아래 줄을 지우고 주석 해제.
    //
    // const user = await this.userService.findById(userId); // firstName/lastName/birthDate는 여기서만 필요
    // const [idCardImage, faceImage] = await Promise.all([
    //   this.downloadImage(client, dto.idCardPath),
    //   this.downloadImage(client, dto.facePath),
    // ]);
    // const form = new FormData();
    // form.append('exam_id', dto.examId);
    // form.append('examinee_id', userId);
    // form.append('captured_at', dto.capturedAt);
    // form.append('first_name', user.firstName);
    // form.append('last_name', user.lastName);
    // form.append('birth_date', user.birthDate ?? '');
    // form.append('source_image', idCardImage.buffer, {
    //   filename: idCardImage.filename,
    //   contentType: idCardImage.contentType,
    // });
    // form.append('target_image', faceImage.buffer, {
    //   filename: faceImage.filename,
    //   contentType: faceImage.contentType,
    // });
    //
    // let aiResponse: FastApiVerifyResponse;
    // try {
    //   const response = await firstValueFrom(
    //     this.httpService.post<FastApiVerifyResponse>(
    //       `${this.config.fastApi.url}/identity/verify`,
    //       form,
    //       { headers: form.getHeaders() },
    //     ),
    //   );
    //   aiResponse = response.data;
    // } catch {
    //   throw new ConflictDomainException(
    //     '본인인증 서비스와 통신에 실패했습니다. 잠시 후 다시 시도해주세요.',
    //   );
    // }
    // // similarity(0~100)를 identity_logs.confidence(0~1) 스케일에 맞춘다.
    // const matched = aiResponse.verified;
    // const confidence = aiResponse.similarity / 100;

    // FastAPI 배포 전 임시값 — 항상 성공한 것으로 처리한다.
    const matched = true;
    const confidence = 1;

    // 4) 결과 로그 저장
    await client.from('identity_logs').insert({
      exam_id: Number(dto.examId),
      user_id: Number(userId),
      id_card_path: dto.idCardPath,
      face_path: dto.facePath,
      matched,
      confidence,
      verified_at: new Date().toISOString(),
    });

    // 5) 원본 이미지는 대조 완료 직후 삭제하는 게 원칙이지만, 아직 실제 대조가
    // 일어나지 않았으므로(위 3번) 재시도를 위해 지금은 남겨둔다.
    // FastAPI 연동 후에는 대조가 끝나는 시점으로 옮겨서 다시 활성화할 것.
    // await client.storage.from('identity-docs').remove([dto.idCardPath, dto.facePath]);

    return { matched, confidence };
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
}
