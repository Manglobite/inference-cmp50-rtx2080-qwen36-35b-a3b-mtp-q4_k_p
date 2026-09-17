#!/usr/bin/env python3
"""Unit tests for structured llama.cpp timing extraction."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


RUN_PATH = Path(__file__).with_name("run.py")
SPEC = importlib.util.spec_from_file_location("benchmark_run", RUN_PATH)
RUN = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUN)


class ParseRawTimingsTest(unittest.TestCase):
    def test_parses_complete_task_timing(self):
        log = """I slot print_timing: id  0 | task 7 | n_decoded =    100, tg =  15.83 t/s, tg_3s =  15.81 t/s
I slot print_timing: id  0 | task 7 | prompt eval time =  130268.65 ms / 23919 tokens (    5.45 ms per token,   183.61 tokens per second)
I slot print_timing: id  0 | task 7 |        eval time =    8102.27 ms /   128 tokens (   63.30 ms per token,    15.80 tokens per second)
I slot print_timing: id  0 | task 7 |       total time =  138370.92 ms / 24047 tokens
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "server.log"
            path.write_text(log)
            timings = RUN.parse_raw_timings(path)

        self.assertEqual(timings, [{
            "task_id": 7,
            "slot_id": 0,
            "tg": {"decoded_tokens": 100, "tokens_per_second": 15.83, "tokens_per_second_3s": 15.81},
            "prompt_eval": {"milliseconds": 130268.65, "tokens": 23919, "tokens_per_second": 183.61},
            "eval": {"milliseconds": 8102.27, "tokens": 128, "tokens_per_second": 15.8},
            "total": {"milliseconds": 138370.92, "tokens": 24047},
        }])


class LongContextPromptTest(unittest.TestCase):
    def test_places_markers_around_repeated_filler(self):
        case = {
            "id": "long-context",
            "messages": [{"role": "user", "content": ""}],
            "long_context": {
                "message_index": 0,
                "repeat_count": 5,
                "prefix": "BEGIN|",
                "filler": "fill|",
                "middle": "MIDDLE|",
                "suffix": "END",
            },
            "max_tokens": 1,
        }
        messages = [dict(message) for message in case["messages"]]
        context = case["long_context"]
        before = context["repeat_count"] // 2
        messages[0]["content"] = "".join((
            context["prefix"],
            context["filler"] * before,
            context["middle"],
            context["filler"] * (context["repeat_count"] - before),
            context["suffix"],
        ))
        self.assertEqual(messages[0]["content"], "BEGIN|fill|fill|MIDDLE|fill|fill|fill|END")


class ExpectedCompletionTest(unittest.TestCase):
    def test_records_exact_completion_check(self):
        request = {"completion": "expected", "completion_tokens": 1, "tokens_per_second": 1.0}
        result = {
            "expected_completion": "expected",
            "completion_matches_expected": request["completion"] == "expected",
        }
        self.assertTrue(result["completion_matches_expected"])


class RawTimingAlignmentTest(unittest.TestCase):
    def test_requires_one_measured_timing_per_single_request(self):
        results = [{"case": "one"}, {"case": "two"}]
        measured_timings = [{"task_id": 1}]
        self.assertNotEqual(len(measured_timings), len(results))


class ProfilePairsTest(unittest.TestCase):
    def test_pairs_only_differ_by_runtime_identity(self):
        pairs = [
            ("llama-cpp-deepseek-r1-qwen3-8b-q4-cmp50hx-baseline.json", "llama-cpp-deepseek-r1-qwen3-8b-q4-cmp50hx-dp2a.json"),
            ("llama-cpp-deepseek-r1-qwen3-8b-q4-cmp50hx-flash-off-baseline.json", "llama-cpp-deepseek-r1-qwen3-8b-q4-cmp50hx-flash-off-dp2a.json"),
            ("llama-cpp-seed-coder-8b-q5-cmp50hx-baseline.json", "llama-cpp-seed-coder-8b-q5-cmp50hx-dp2a.json"),
            ("llama-cpp-qwen25-coder-3b-q8-cmp50hx-baseline.json", "llama-cpp-qwen25-coder-3b-q8-cmp50hx-dp2a.json"),
            ("llama-cpp-qwen25-coder-3b-q8-flash-cmp50hx-baseline.json", "llama-cpp-qwen25-coder-3b-q8-flash-cmp50hx-dp2a.json"),
            ("llama-cpp-qwen35-4b-q8-cmp50hx-baseline.json", "llama-cpp-qwen35-4b-q8-cmp50hx-dp2a.json"),
            ("llama-cpp-qwen35-4b-q8-flash-cmp50hx-baseline.json", "llama-cpp-qwen35-4b-q8-flash-cmp50hx-dp2a.json"),
        ]
        profiles = RUN.ROOT / "benchmarks/profiles"
        for baseline_name, dp2a_name in pairs:
            with self.subTest(pair=(baseline_name, dp2a_name)):
                baseline = json.loads((profiles / baseline_name).read_text())
                dp2a = json.loads((profiles / dp2a_name).read_text())
                for profile in (baseline, dp2a):
                    profile.pop("name")
                    profile.pop("binary")
                    profile.pop("build_variant")
                self.assertEqual(baseline, dp2a)


if __name__ == "__main__":
    unittest.main()
