import { Injectable } from '@nestjs/common';
import {
  IdentityProviderPort,
  VerifyIdentityResult,
} from '../../domain/ports/identity-provider.port';

/**
 * MOCK_IDENTITY_VERIFICATION=true일 때만 실제 FastApiIdentityAdapter 대신 쓰이는
 * 테스트용 어댑터(ai.module.ts 참고) — anti-cheat를 호출하지 않고 입력 이미지와
 * 무관하게 항상 성공을 반환한다. QA가 아무 사진으로 본인인증을 통과시켜 시험
 * 흐름 전체를 테스트할 때 쓴다.
 */
@Injectable()
export class MockIdentityAdapter implements IdentityProviderPort {
  verify(): Promise<VerifyIdentityResult> {
    return Promise.resolve({
      verified: true,
      faceVerified: true,
      similarity: 100,
      threshold: 80,
      matchedFaceCount: 1,
      unmatchedFaceCount: 0,
      applicantVerified: true,
      documentType: 'passport',
      fieldMatches: {},
      message: 'MOCK_IDENTITY_VERIFICATION=true — anti-cheat 호출 없이 항상 통과 처리됨.',
      raw: { mocked: true },
    });
  }
}
