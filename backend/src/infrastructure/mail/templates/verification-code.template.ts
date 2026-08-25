interface VerificationCodeEmailContent {
  subject: string;
  text: string;
  html: string;
}

/** 이메일 클라이언트 호환성 때문에 <style> 대신 인라인 스타일 + 테이블 레이아웃을 쓴다. */
export function buildVerificationCodeEmail(code: string): VerificationCodeEmailContent {
  const subject = '[K-TEST] Email verification code';
  const text = `[K-TEST] Email verification code\n\n${code}\n\nPlease enter it within 10 minutes.\nIf you did not request this, you can safely ignore this email.`;

  const html = `
<!doctype html>
<html lang="en">
  <body style="margin:0; padding:0; background-color:#f4f5f7; font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">
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
                <p style="margin:0 0 8px; color:#111827; font-size:16px; font-weight:600;">Email verification code</p>
                <p style="margin:0 0 24px; color:#6b7280; font-size:14px; line-height:1.5;">
                  Enter the code below to complete email verification.
                </p>
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0">
                  <tr>
                    <td align="center" style="background-color:#f4f5f7; border-radius:8px; padding:20px;">
                      <span style="font-size:32px; font-weight:700; letter-spacing:8px; color:#1a56db;">${code}</span>
                    </td>
                  </tr>
                </table>
                <p style="margin:20px 0 0; color:#9ca3af; font-size:13px; line-height:1.5;">
                  This code is valid for <strong style="color:#6b7280;">10 minutes</strong>.<br />
                  If you did not request this, you can safely ignore this email.
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:16px 32px; background-color:#f9fafb; border-top:1px solid #f0f0f0;">
                <p style="margin:0; color:#9ca3af; font-size:12px;">© K-TEST. This is an automated message; please do not reply.</p>
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
