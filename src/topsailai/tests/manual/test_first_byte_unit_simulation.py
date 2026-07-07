#!/usr/bin/env python3
"""
Simulation script to verify tokenStat first-byte timing unit.

It demonstrates the difference between:
- Correct behavior: storing latency in milliseconds (ms).
- Incorrect behavior: storing latency in seconds (s) under keys named `_ms`.
"""

from topsailai.context.token import TokenStat


def simulate_known_delays_ms():
    """Simulate first-byte delays as milliseconds (correct unit)."""
    stat = TokenStat(llm_id="test-ms")
    # Known delays: 0.5s, 1.5s, 2.5s -> converted to ms
    delays_ms = [500.0, 1500.0, 2500.0]
    for d in delays_ms:
        stat.add_first_byte(d)
    return stat.output_token_stat()


def simulate_known_delays_s_mislabeled():
    """Simulate first-byte delays as seconds stored under _ms keys (wrong unit)."""
    stat = TokenStat(llm_id="test-s")
    # Same delays, but stored as seconds instead of milliseconds
    delays_s = [0.5, 1.5, 2.5]
    for d in delays_s:
        stat.add_first_byte(d)
    return stat.output_token_stat()


if __name__ == "__main__":
    print("=" * 60)
    print("First-byte unit simulation")
    print("=" * 60)

    print("\n[Case A] Correct: add_first_byte() receives milliseconds")
    print("Input delays: 500ms, 1500ms, 2500ms")
    result_ms = simulate_known_delays_ms()
    print(f"Output: {result_ms}")

    print("\n[Case B] Wrong: add_first_byte() receives seconds")
    print("Input delays: 0.5s, 1.5s, 2.5s")
    result_s = simulate_known_delays_s_mislabeled()
    print(f"Output: {result_s}")

    print("\n" + "=" * 60)
    print("Interpretation:")
    print("- Case A reports avg=1500.0 ms, which matches 1.5 seconds.")
    print("- Case B reports avg=1.5 ms, which looks like seconds but is labeled ms.")
    print("If you see values like 2.351 / 5.535 / 0.573 under _ms keys,")
    print("your runtime is behaving like Case B (seconds stored as ms).")
    print("=" * 60)
