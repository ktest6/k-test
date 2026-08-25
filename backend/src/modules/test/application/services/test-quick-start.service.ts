import { Inject, Injectable } from '@nestjs/common';
import { ConfigType } from '@nestjs/config';
import { appConfig } from '../../../../config/configuration';
import {
  ConflictDomainException,
  ForbiddenDomainException,
} from '../../../../common/exceptions/domain.exception';
import { NOT_AVAILABLE_IN_PRODUCTION } from '../../../../common/exceptions/error-messages';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { AuthService } from '../../../auth/application/services/auth.service';
import { ExamSessionService } from '../../../exam-session/application/services/exam-session.service';
import { UserService } from '../../../user/application/services/user.service';
import { QuickStartResponseDto } from '../dto/quick-start-response.dto';

/**
 * 테스트 전용 — "회원가입 → 본인인증(신분증/이어폰/시선) → 시험 응시" 전체
 * 온보딩을 건너뛰고 곧바로 문항을 풀 수 있는 상태(세션 생성 + verified:true)를
 * 한 번에 만든다. 실제 채점(assessment)·리포트(mypage/report)는 기존
 * 엔드포인트를 그대로 쓰면 되므로 여기서 다루지 않는다 — 이 유틸리티가 만드는
 * 건 딱 "검증 끝난 세션 + 그 세션으로 바로 쓸 토큰"까지다.
 *
 * 본인인증/이어폰체크는 실제로 FastAPI를 호출하는 대신, 그 결과가 성공했을 때와
 * 완전히 같은 모양의 로그 행을 tb_identity_logs/tb_earphone_logs에 직접 심는다
 * — ExamSessionService.isVerified()가 그 로그의 존재 여부만으로 판단하기
 * 때문에, 실제 검증 플로우를 통과한 것과 프로덕션 코드 경로상 구분이 안 된다.
 * TestResetService와 같은 이유로 프로덕션에서는 항상 거부한다.
 */
@Injectable()
export class TestQuickStartService {
  constructor(
    private readonly userService: UserService,
    private readonly examSessionService: ExamSessionService,
    private readonly authService: AuthService,
    private readonly supabaseService: SupabaseService,
    @Inject(appConfig.KEY) private readonly config: ConfigType<typeof appConfig>,
  ) {}

  async quickStart(): Promise<QuickStartResponseDto> {
    if (this.config.env === 'production') {
      throw new ForbiddenDomainException(NOT_AVAILABLE_IN_PRODUCTION);
    }

    const now = new Date();
    const email = `test-quick-${Date.now()}-${Math.random().toString(36).slice(2, 8)}@ktest.local`;

    const user = await this.userService.register({
      email,
      password: 'TestQuickStart1234!!',
      firstName: 'TEST',
      lastName: 'USER',
      nationality: 'KOR',
      birthDate: '2000-01-01',
      termsAgreedAt: now,
      privacyAgreedAt: now,
      passportProcessingAgreedAt: now,
      emailVerifiedAt: now,
      voiceDataAiTrainingAgreedAt: null,
    });

    const session = await this.examSessionService.start(user.id);

    await this.seedPassingVerificationLogs(session.id, now);

    const auth = this.authService.issueTestAccessToken(user.id, user.email);

    return {
      accessToken: auth.accessToken,
      userId: user.id,
      email: user.email,
      examSessionId: session.id,
      status: session.status,
      verified: true,
    };
  }

  /** 실제 본인인증/이어폰체크가 성공했을 때와 동일한 로그를 남겨 검증 게이트를 통과시킨다. */
  private async seedPassingVerificationLogs(examSessionId: string, now: Date): Promise<void> {
    const client = this.supabaseService.getAdminClient();

    const { error: identityError } = await client.from('tb_identity_logs').insert({
      exam_session_id: Number(examSessionId),
      id_card_path: 'test-quick-start/bypass',
      face_path: 'test-quick-start/bypass',
      matched: true,
      confidence: 1,
      document_type: 'passport',
      verified_at: now.toISOString(),
    });
    if (identityError) {
      throw new ConflictDomainException(
        `Failed to create identity verification bypass record: ${identityError.message}`,
      );
    }

    const { error: earphoneError } = await client.from('tb_earphone_logs').insert({
      exam_session_id: Number(examSessionId),
      earphone_detected: false,
      checked_at: now.toISOString(),
    });
    if (earphoneError) {
      throw new ConflictDomainException(
        `Failed to create earphone check bypass record: ${earphoneError.message}`,
      );
    }
  }
}
