-- =========================================================
-- tb_earphone_logs: inspection_complete 추가
-- =========================================================
-- anti-cheat 쪽 /earphone/detect 응답이 얼굴 yaw 기반 자세 조건을 추가해서,
-- earphone_detected가 신뢰할 수 있는 값인지(양쪽 귀가 다 보이는 자세에서
-- 판정이 끝났는지)를 별도로 알려주게 됐다. 정면만 보고 있어서 귀가 안 보이면
-- earphone_detected=false가 나올 수 있는데, 이걸 그냥 "이어폰 없음(통과)"로
-- 인정하면 실제로 착용했는데도 통과하는 구멍이 생긴다 — 그래서 이 값이
-- true일 때만 earphone_detected를 신뢰하도록 통과 판정 조건에 추가한다
-- (EarphoneDetectionService.hasPassedCheck 참고).
--
-- 이 컬럼 도입 이전 기록은 이런 자세 검증 개념 자체가 없던 구 판정 방식이라
-- 항상 완료로 간주해 기본값 true로 채운다.

alter table tb_earphone_logs
  add column inspection_complete boolean not null default true;

alter table tb_earphone_logs
  alter column inspection_complete drop default;

comment on column tb_earphone_logs.inspection_complete is
  '양쪽 귀가 보이는 자세에서 검사가 완료됐는지 여부. false면 자세 문제로 판정 자체가'
  ' 불완전한 상태라 earphone_detected 값을 신뢰할 수 없다 — 통과 판정은 이 값이 true일'
  ' 때만 인정한다.';
