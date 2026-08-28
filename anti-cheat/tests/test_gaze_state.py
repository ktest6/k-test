"""눈과 고개 이탈 상태의 독립 누적을 검증한다."""

import unittest

from modules.cheating_detection.rule_engine import evaluate_gaze_rules
from modules.cheating_detection.gaze_state import update_gaze_state


def gaze_result(
    event_type: str,
    *,
    eye_away: bool = False,
    head_away: bool = False,
    head_level: str = "NORMAL",
) -> dict[str, object]:
    return {
        "event_type": event_type,
        "direction": "UNKNOWN",
        "eye_gaze_away": eye_away,
        "head_pose_away": head_away,
        "head_pose_level": head_level,
    }


def update(
    result: dict[str, object],
    sequence: int,
    previous: dict[str, object] | None = None,
) -> dict[str, object]:
    return update_gaze_state(
        gaze_monitor_result=result,
        elapsed_ms=sequence * 1000,
        capture_sequence=sequence,
        persistent_count_threshold=3,
        previous_state=previous,
    )


class GazeStateTest(unittest.TestCase):
    def test_eye_count_survives_eye_and_head_transition(self) -> None:
        state = update(gaze_result("GAZE_AWAY", eye_away=True), 1)
        state = update(
            gaze_result("GAZE_AWAY", eye_away=True, head_away=True),
            2,
            state,
        )
        state = update(
            gaze_result("GAZE_AWAY", eye_away=True),
            3,
            state,
        )

        self.assertEqual(state["consecutive_eye_away_count"], 3)
        self.assertEqual(state["consecutive_head_away_count"], 0)

    def test_head_count_survives_eye_and_head_transition(self) -> None:
        state = update(
            gaze_result(
                "GAZE_AWAY",
                head_away=True,
                head_level="SLIGHT",
            ),
            1,
        )
        state = update(
            gaze_result(
                "GAZE_AWAY",
                eye_away=True,
                head_away=True,
                head_level="SLIGHT",
            ),
            2,
            state,
        )
        state = update(
            gaze_result(
                "GAZE_AWAY",
                head_away=True,
                head_level="SLIGHT",
            ),
            3,
            state,
        )

        self.assertEqual(state["consecutive_head_away_count"], 3)
        self.assertEqual(state["consecutive_eye_away_count"], 0)

    def test_uncertain_frame_breaks_away_state(self) -> None:
        state = update(gaze_result("GAZE_AWAY", eye_away=True), 1)
        state = update(gaze_result("GAZE_UNCERTAIN"), 2, state)
        state = update(
            gaze_result("GAZE_AWAY", eye_away=True),
            3,
            state,
        )

        self.assertEqual(state["consecutive_away_count"], 1)
        self.assertEqual(state["consecutive_eye_away_count"], 1)
        self.assertEqual(state["away_duration_ms"], 0)

    def test_not_analyzed_frame_breaks_away_state(self) -> None:
        state = update(gaze_result("GAZE_AWAY", head_away=True), 1)
        state = update(gaze_result("GAZE_NOT_ANALYZED"), 2, state)

        self.assertEqual(state["consecutive_away_count"], 0)
        self.assertEqual(state["consecutive_head_away_count"], 0)
        self.assertIsNone(state["away_started_elapsed_ms"])

    def test_slight_head_is_medium_at_five_and_high_at_fifteen(self) -> None:
        state = None
        result = gaze_result(
            "GAZE_AWAY",
            head_away=True,
            head_level="SLIGHT",
        )
        fifth_rules = []

        for sequence in range(1, 16):
            state = update(result, sequence, state)
            result["state"] = state
            rules = evaluate_gaze_rules(result)
            if sequence == 5:
                fifth_rules = rules

        self.assertEqual(fifth_rules[0]["severity"], "MEDIUM")
        self.assertEqual(rules[0]["severity"], "HIGH")
        self.assertEqual(rules[0]["decision"], "CREATE_CLIP")

    def test_large_head_escalates_on_each_of_first_three_frames(self) -> None:
        state = None
        result = gaze_result(
            "GAZE_AWAY",
            head_away=True,
            head_level="LARGE",
        )
        severities = []

        for sequence in range(1, 4):
            state = update(result, sequence, state)
            result["state"] = state
            severities.append(evaluate_gaze_rules(result)[0]["severity"])

        self.assertEqual(severities, ["LOW", "MEDIUM", "HIGH"])

    def test_changing_head_level_restarts_level_count(self) -> None:
        slight = gaze_result(
            "GAZE_AWAY",
            head_away=True,
            head_level="SLIGHT",
        )
        state = update(slight, 1)
        large = gaze_result(
            "GAZE_AWAY",
            head_away=True,
            head_level="LARGE",
        )
        state = update(large, 2, state)
        large["state"] = state

        rules = evaluate_gaze_rules(large)

        self.assertEqual(state["consecutive_head_large_count"], 1)
        self.assertEqual(state["consecutive_head_slight_count"], 0)
        self.assertEqual(rules[0]["severity"], "LOW")

    def test_eye_rule_reaches_high_across_type_changes(self) -> None:
        result = gaze_result("GAZE_AWAY", eye_away=True)
        state = update(result, 1)
        result = gaze_result(
            "GAZE_AWAY",
            eye_away=True,
            head_away=True,
        )
        state = update(result, 2, state)
        result = gaze_result("GAZE_AWAY", eye_away=True)
        state = update(result, 3, state)
        result["state"] = state

        rules = evaluate_gaze_rules(result)

        self.assertEqual(rules[0]["rule_id"], "RULE_EYE_GAZE_AWAY")
        self.assertEqual(rules[0]["severity"], "HIGH")
        self.assertEqual(rules[0]["decision"], "CREATE_CLIP")


if __name__ == "__main__":
    unittest.main()
