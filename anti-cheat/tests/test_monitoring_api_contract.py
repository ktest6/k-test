"""모니터링 API의 필수 요청 계약을 검증한다."""

import unittest

from app.main import app


class MonitoringApiContractTest(unittest.TestCase):
    def test_all_calibration_centers_are_required(self) -> None:
        schema = app.openapi()
        body_schema = schema["components"]["schemas"][
            "Body_analyze_frame_monitoring_analyze_post"
        ]
        required = set(body_schema["required"])

        self.assertTrue(
            {
                "eye_yaw_center",
                "eye_pitch_center",
                "head_yaw_center",
                "head_pitch_center",
            }.issubset(required)
        )


if __name__ == "__main__":
    unittest.main()
