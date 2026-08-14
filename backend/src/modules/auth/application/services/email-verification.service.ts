import { randomInt } from 'node:crypto';
import { Injectable } from '@nestjs/common';
import { ConflictDomainException } from '../../../../common/exceptions/domain.exception';
import { SupabaseService } from '../../../../infrastructure/supabase/supabase.service';
import { UserService } from '../../../user/application/services/user.service';

const TABLE = 'tb_email_verification';
const CODE_TTL_MINUTES = 10;
const MAX_ATTEMPTS = 5;

interface VerificationRow {
  email: string;
  code: string;
  code_expires_at: string;
  attempts: number;
  verified_at: string | null;
}

/**
 * 가입 "전" 이메일 인증. 이 시점엔 아직 tb_user row가 없으므로 이메일 기준의
 * 별도 테이블(tb_email_verification)에 코드/시도횟수/인증여부를 들고 있다가,
 * 가입이 실제로 완료되면(consumeVerification) 그 행을 지운다.
 */
@Injectable()
export class EmailVerificationService {
  constructor(
    private readonly supabaseService: SupabaseService,
    private readonly userService: UserService,
  ) {}

  /** 이미 가입된 이메일이면 막고, 아니면 새 코드를 발급해 저장한 뒤 그대로 반환한다(발송은 호출부의 몫). */
  async sendCode(email: string): Promise<string> {
    const taken = await this.userService.existsByEmail(email);
    if (taken) {
      throw new ConflictDomainException('이미 사용 중인 이메일입니다.');
    }

    const code = randomInt(0, 1_000_000).toString().padStart(6, '0');
    const codeExpiresAt = new Date(Date.now() + CODE_TTL_MINUTES * 60_000);

    const client = this.supabaseService.getAdminClient();
    const { error } = await client.from(TABLE).upsert(
      {
        email,
        code,
        code_expires_at: codeExpiresAt.toISOString(),
        attempts: 0,
        verified_at: null,
      },
      { onConflict: 'email' },
    );
    if (error) {
      throw new ConflictDomainException(error.message ?? '인증번호 저장에 실패했습니다.');
    }

    return code;
  }

  async verifyCode(email: string, code: string): Promise<void> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('*')
      .eq('email', email)
      .maybeSingle<VerificationRow>();

    if (!data) {
      throw new ConflictDomainException('인증번호가 올바르지 않습니다.');
    }
    if (data.verified_at) {
      throw new ConflictDomainException('이미 인증된 이메일입니다.');
    }
    if (new Date(data.code_expires_at).getTime() < Date.now()) {
      throw new ConflictDomainException('인증번호가 만료되었습니다. 다시 요청해주세요.');
    }
    if (data.attempts >= MAX_ATTEMPTS) {
      throw new ConflictDomainException(
        '인증 시도 횟수를 초과했습니다. 인증번호를 다시 요청해주세요.',
      );
    }
    if (data.code !== code) {
      await client
        .from(TABLE)
        .update({ attempts: data.attempts + 1 })
        .eq('email', email);
      throw new ConflictDomainException('인증번호가 올바르지 않습니다.');
    }

    const { error } = await client
      .from(TABLE)
      .update({ verified_at: new Date().toISOString() })
      .eq('email', email);
    if (error) {
      throw new ConflictDomainException(error.message ?? '이메일 인증 처리에 실패했습니다.');
    }
  }

  /** 가입 완료 직전 호출 — 인증됐는지 확인하고, 확인됐으면 대기 행을 정리하며 인증 시각을 돌려준다. */
  async consumeVerification(email: string): Promise<Date> {
    const client = this.supabaseService.getAdminClient();
    const { data } = await client
      .from(TABLE)
      .select('verified_at')
      .eq('email', email)
      .maybeSingle<{ verified_at: string | null }>();

    if (!data?.verified_at) {
      throw new ConflictDomainException('이메일 인증을 먼저 완료해주세요.');
    }

    const verifiedAt = new Date(data.verified_at);
    await client.from(TABLE).delete().eq('email', email);
    return verifiedAt;
  }
}
