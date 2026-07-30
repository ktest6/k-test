import { Injectable } from '@nestjs/common';
import { ForbiddenDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { VerifyIdCardDto } from '../dto/verify-id-card.dto';
import { VerifyIdCardResponseDto } from '../dto/verify-id-card-response.dto';
import { ExamSessionAccessService } from './exam-session-access.service';

/**
 * 시험 시작 전 본인인증(신분증-얼굴 대조). 이미지 자체는 프론트가
 * POST /verifications/id-card/upload-url로 발급받은 signed URL로 Supabase
 * Storage에 직접 올리고, 여기서는 그 경로만 받아 소유권을 검증한 뒤 얼굴
 * 대조를 맡을 FastAPI 서비스에 넘긴다 — FastAPI 연동 전까지는 대조 호출을
 * 생략하고 matched/confidence를 null로 기록한다 (아래 TODO 참고).
 */
@Injectable()
export class IdCardVerificationService {
  constructor(
    private readonly supabaseService: SupabaseService,
    private readonly examSessionAccessService: ExamSessionAccessService,
  ) {}

  async verify(userId: string, dto: VerifyIdCardDto): Promise<VerifyIdCardResponseDto> {
    const client = this.supabaseService.getAdminClient();

    // 1) 전달받은 경로가 실제로 이 사용자 소유 폴더 아래인지 확인.
    // upload-url 발급 단계에서 이미 서버가 경로를 정해줬으므로(바꿔치기 불가),
    // 여기서는 그 경로가 그대로 전달됐는지 한 번 더 확인하는 방어 계층이다.
    const expectedPrefix = `${userId}/${dto.examSessionId}/`;
    if (!dto.idCardPath.startsWith(expectedPrefix) || !dto.facePath.startsWith(expectedPrefix)) {
      throw new ForbiddenDomainException('본인 파일 경로가 아닙니다.');
    }

    // 2) 세션 소유자 확인
    await this.examSessionAccessService.assertOwnership(userId, dto.examSessionId);

    // 3) FastAPI(VM)로 얼굴 대조 요청
    // TODO: FastAPI 연동 준비되면 주석 해제.
    //   - `npm install @nestjs/axios axios`, HttpService를 이 서비스에 주입
    //   - FASTAPI_URL을 config/validation.schema.ts + .env.example에 추가
    //
    // const aiResponse = await firstValueFrom(
    //   this.httpService.post<{ matched: boolean; confidence: number }>(
    //     `${this.config.fastApiUrl}/identity/compare`,
    //     { idCardPath: dto.idCardPath, facePath: dto.facePath },
    //   ),
    // );
    // const { matched, confidence } = aiResponse.data;
    //
    // 연동 전까지는 실제 대조 없이 null로 기록한다. 절대 matched: true 같은
    // 임의 값을 채우지 않는다 — 본인인증은 보안에 직결되므로 "아직 검증되지
    // 않음"과 "검증 결과 불일치"를 명확히 구분해야 한다.
    const matched: boolean | null = null;
    const confidence: number | null = null;

    // 4) 결과 로그 저장
    await client.from('identity_logs').insert({
      exam_session_id: Number(dto.examSessionId),
      id_card_path: dto.idCardPath,
      face_path: dto.facePath,
      matched,
      confidence,
      verified_at: matched === null ? null : new Date().toISOString(),
    });

    // 5) 원본 이미지는 대조 완료 직후 삭제하는 게 원칙이지만, 아직 대조가
    // 실제로 일어나지 않았으므로(위 3번) 재시도를 위해 지금은 남겨둔다.
    // FastAPI 연동 후에는 대조가 끝나는 시점(matched/confidence를 얻은
    // 직후)으로 옮겨서 다시 활성화할 것.
    // await client.storage.from('identity-docs').remove([dto.idCardPath, dto.facePath]);

    return { matched, confidence };
  }
}
