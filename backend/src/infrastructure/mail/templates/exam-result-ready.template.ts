interface ExamResultReadyEmailContent {
  subject: string;
  text: string;
  html: string;
}

/** 실제 점수/등급은 담지 않는다 — 로그인해서 확인하도록 안내만 한다(민감한 채점 정보를 메일 본문에 남기지 않기 위함). */
export function buildExamResultReadyEmail(): ExamResultReadyEmailContent {
  const subject = '[K-TEST] Your exam results are ready';
  const text = `[K-TEST] The results for your exam are ready.\n\nPlease log in to K-TEST to view your results.`;

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
                <p style="margin:0 0 8px; color:#111827; font-size:16px; font-weight:600;">Your exam results are ready</p>
                <p style="margin:0 0 24px; color:#6b7280; font-size:14px; line-height:1.5;">
                  The results for your exam are ready.<br />
                  Please log in to K-TEST to view your results.
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
