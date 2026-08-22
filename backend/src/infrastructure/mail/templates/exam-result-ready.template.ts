interface ExamResultReadyEmailContent {
  subject: string;
  text: string;
  html: string;
}

/** 실제 점수/등급은 담지 않는다 — 로그인해서 확인하도록 안내만 한다(민감한 채점 정보를 메일 본문에 남기지 않기 위함). */
export function buildExamResultReadyEmail(): ExamResultReadyEmailContent {
  const subject = '[K-TEST] 채점 결과가 준비되었습니다';
  const text = `[K-TEST] 응시하신 시험의 채점 결과가 준비되었습니다.\n\nK-TEST에 로그인해서 결과를 확인해주세요.`;

  const html = `
<!doctype html>
<html lang="ko">
  <body style="margin:0; padding:0; background-color:#f4f5f7; font-family:'Apple SD Gothic Neo','Malgun Gothic',Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f5f7; padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:420px; background-color:#ffffff; border-radius:12px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.08);">
            <tr>
              <td style="background-color:#1a56db; padding:24px 32px;">
                <span style="color:#ffffff; font-size:18px; font-weight:700; letter-spacing:0.5px;">K-TEST</span>
              </td>
            </tr>
            <tr>
              <td style="padding:32px;">
                <p style="margin:0 0 8px; color:#111827; font-size:16px; font-weight:600;">채점 결과가 준비되었습니다</p>
                <p style="margin:0 0 24px; color:#6b7280; font-size:14px; line-height:1.5;">
                  응시하신 시험의 채점 결과가 준비되었습니다.<br />
                  K-TEST에 로그인해서 결과를 확인해주세요.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 32px; background-color:#f9fafb; border-top:1px solid #f0f0f0;">
                <p style="margin:0; color:#9ca3af; font-size:12px;">© K-TEST. 본 메일은 발신 전용입니다.</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
`.trim();

  return { subject, text, html };
}
