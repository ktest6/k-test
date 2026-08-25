interface DisqualifiedEmailContent {
  subject: string;
  text: string;
  html: string;
}

/** K-TEST 응시 시각은 한국에서 진행되므로 한국 표준시 기준으로 표시한다. */
function formatStartedAt(startedAt: Date): string {
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'Asia/Seoul',
    dateStyle: 'long',
    timeStyle: 'short',
  }).format(startedAt);
}

/**
 * reason은 부정행위 종류(프런트 감지) 또는 관리자 검토 사유 등 실격 처리 시점에 확정된 사유 문구,
 * startedAt은 실격된 세션이 시작된 시각(응시자가 "어느 시험이 실격됐는지" 바로 알 수 있게).
 */
export function buildDisqualifiedEmail(reason: string, startedAt: Date): DisqualifiedEmailContent {
  const formattedStartedAt = formatStartedAt(startedAt);
  const subject = '[K-TEST] Your exam has been disqualified';
  const text = `[K-TEST] Your exam started on ${formattedStartedAt} (KST) has been disqualified.\n\nReason: ${reason}\n\nIf you have any questions, please contact customer support.`;

  const html = `
<!doctype html>
<html lang="en">
  <body style="margin:0; padding:0; background-color:#f4f5f7; font-family:-apple-system,'Segoe UI',Helvetica,Arial,sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#f4f5f7; padding:32px 16px;">
      <tr>
        <td align="center">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:420px; background-color:#ffffff; border-radius:12px; overflow:hidden; box-shadow:0 1px 3px rgba(0,0,0,0.08);">
            <tr>
              <td style="background-color:#dc2626; padding:24px 32px;">
                <span style="color:#ffffff; font-size:18px; font-weight:700; letter-spacing:0.5px;">K-TEST</span>
              </td>
            </tr>
            <tr>
              <td style="padding:32px;">
                <p style="margin:0 0 8px; color:#111827; font-size:16px; font-weight:600;">Your exam has been disqualified</p>
                <p style="margin:0 0 16px; color:#6b7280; font-size:14px; line-height:1.5;">
                  Your exam started on <strong style="color:#111827;">${formattedStartedAt} (KST)</strong> has been disqualified under our anti-cheating policy.
                </p>
                <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#fef2f2; border-radius:8px; margin:0 0 24px;">
                  <tr>
                    <td style="padding:12px 16px;">
                      <p style="margin:0; color:#991b1b; font-size:13px; line-height:1.5;">Reason: ${reason}</p>
                    </td>
                  </tr>
                </table>
                <p style="margin:0; color:#6b7280; font-size:13px; line-height:1.5;">
                  If you have any questions, please contact customer support.
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
