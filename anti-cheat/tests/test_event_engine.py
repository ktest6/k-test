"""Rule 결과가 외부 이벤트 응답에 보존되는지 검증한다."""

import unittest

from modules.cheating_detection.event_engine import transform_rule_result


class EventEngineTest(unittest.TestCase):
    def test_event_includes_rule_metadata(self) -> None:
        result = transform_rule_result(
            {
                "applied_rules": [
                    {
                        "rule_id": "RULE_PHONE_DETECTED",
                        "event_type": "PHONE_DETECTED",
                        "severity": "HIGH",
                        "decision": "CREATE_CLIP",
                        "message": "휴대폰이 탐지되었습니다.",
                        "details": {
                            "confidence": 95.0,
                        },
                    }
                ],
                "severity": "HIGH",
                "decision": "CREATE_CLIP",
            }
        )

        self.assertEqual(
            result["events"],
            [
                {
                    "rule_id": "RULE_PHONE_DETECTED",
                    "event_type": "PHONE_DETECTED",
                    "severity": "HIGH",
                    "decision": "CREATE_CLIP",
                    "message": "휴대폰이 탐지되었습니다.",
                    "details": {
                        "confidence": 95.0,
                    },
                }
            ],
        )
        self.assertEqual(
            result["event_summary"]["decision"],
            "CREATE_CLIP",
        )


if __name__ == "__main__":
    unittest.main()
