"""
Minimal smoke test for InfoHunter GEP Self-Healer.

Verifies: signal → gene match → repair action → capsule record.
"""

import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.self_healer import SelfHealer, CAPSULES_PATH


def test_gene_loading():
    healer = SelfHealer()
    assert healer.genes is not None
    assert len(healer.genes) >= 4, f"Expected ≥4 genes, got {len(healer.genes)}"
    gene_ids = {g["id"] for g in healer.genes}
    expected = {
        "gene_youtube_oauth_refresh",
        "gene_rss_ssl_retry",
        "gene_api_rate_limit_backoff",
        "gene_analysis_failure_recovery",
    }
    assert expected.issubset(gene_ids), f"Missing: {expected - gene_ids}"
    print(f"  ✓ Loaded {len(healer.genes)} genes: {', '.join(gene_ids)}")


def test_signal_matching():
    healer = SelfHealer()

    gene = healer.match_gene("youtube oauth token expired or revoked")
    assert gene is not None
    assert gene["id"] == "gene_youtube_oauth_refresh"
    print(f"  ✓ youtube oauth expired → {gene['id']}")

    gene2 = healer.match_gene("ssl connection error during tls handshake")
    assert gene2 is not None
    assert gene2["id"] == "gene_rss_ssl_retry"
    print(f"  ✓ ssl error → {gene2['id']}")

    gene3 = healer.match_gene("429 too many requests rate limit exceeded")
    assert gene3 is not None
    assert gene3["id"] == "gene_api_rate_limit_backoff"
    print(f"  ✓ rate limit → {gene3['id']}")

    gene4 = healer.match_gene("content_analyzer analysis failed timeout")
    assert gene4 is not None
    assert gene4["id"] == "gene_analysis_failure_recovery"
    print(f"  ✓ analysis failure → {gene4['id']}")

    none_gene = healer.match_gene("everything is fine no issues")
    assert none_gene is None
    print("  ✓ no match for benign signal (correct)")


def test_ssl_skiplist_repair():
    healer = SelfHealer()

    with tempfile.TemporaryDirectory() as tmpdir:
        import src.self_healer as sh
        original = sh.CAPSULES_PATH
        sh.CAPSULES_PATH = Path(tmpdir) / "caps.jsonl"

        capsule = healer.attempt_heal(
            error_signal="ssl certificate verify failed for feed",
            source_name="rss",
            error_detail="SSLError: certificate verify failed",
            context={"feed_url": "https://example.com/feed.xml"},
        )

        assert capsule is not None
        assert capsule["gene_id"] == "gene_rss_ssl_retry"
        assert capsule["outcome"]["status"] == "success"
        assert capsule["trigger"] == ["rss", "ssl certificate verify failed for feed"]
        print(f"  ✓ SSL repair capsule: {capsule['id']}, status={capsule['outcome']['status']}")

        skiplist_path = Path(__file__).parent / "logs" / "ssl_skiplist.json"
        if skiplist_path.exists():
            with open(skiplist_path) as f:
                skiplist = json.load(f)
            assert "https://example.com/feed.xml" in skiplist
            print(f"  ✓ Feed added to SSL skiplist ({len(skiplist)} entries)")
            skiplist.remove("https://example.com/feed.xml")
            with open(skiplist_path, "w") as f:
                json.dump(skiplist, f)

        sh.CAPSULES_PATH = original


def test_backoff_repair():
    healer = SelfHealer()

    with tempfile.TemporaryDirectory() as tmpdir:
        import src.self_healer as sh
        original = sh.CAPSULES_PATH
        sh.CAPSULES_PATH = Path(tmpdir) / "caps.jsonl"

        capsule = healer.attempt_heal(
            error_signal="429 too many requests rate limit",
            source_name="twitter",
            error_detail="Rate limit exceeded",
        )

        assert capsule is not None
        assert capsule["gene_id"] == "gene_api_rate_limit_backoff"
        assert capsule["outcome"]["status"] == "success"
        print(f"  ✓ Backoff capsule: {capsule['id']}")

        backoff_path = Path(__file__).parent / "logs" / "backoff_state.json"
        if backoff_path.exists():
            with open(backoff_path) as f:
                state = json.load(f)
            assert "twitter" in state
            print(f"  ✓ Backoff state: delay={state['twitter']['delay_seconds']}s, factor={state['twitter']['batch_factor']}")
            del state["twitter"]
            with open(backoff_path, "w") as f:
                json.dump(state, f)

        sh.CAPSULES_PATH = original


def test_stats():
    healer = SelfHealer()
    stats = healer.get_stats()
    assert "total_attempts" in stats
    assert "genes_loaded" in stats
    assert stats["genes_loaded"] >= 4
    print(f"  ✓ Stats: {stats['genes_loaded']} genes loaded, {stats['total_attempts']} historical attempts")


def test_cooldown():
    healer = SelfHealer()
    healer._cooldowns.clear()

    gene1 = healer.match_gene("ssl error connection failed")
    assert gene1 is not None
    healer._set_cooldown(gene1["id"])

    gene2 = healer.match_gene("ssl error connection failed")
    assert gene2 is None, "Should be in cooldown"
    print("  ✓ Cooldown prevents re-match")

    healer._cooldowns.clear()


def main():
    print("\n=== InfoHunter Self-Healer Smoke Tests ===\n")

    tests = [
        ("Gene Loading", test_gene_loading),
        ("Signal Matching", test_signal_matching),
        ("SSL Skiplist Repair", test_ssl_skiplist_repair),
        ("Backoff Repair", test_backoff_repair),
        ("Stats Aggregation", test_stats),
        ("Cooldown", test_cooldown),
    ]

    passed = 0
    failed = 0
    for name, fn in tests:
        try:
            print(f"[{name}]")
            fn()
            passed += 1
        except Exception as e:
            print(f"  ✗ FAILED: {e}")
            import traceback
            traceback.print_exc()
            failed += 1
        print()

    print(f"{'=' * 40}")
    print(f"Results: {passed} passed, {failed} failed")
    if failed == 0:
        print("All tests passed! InfoHunter self-healing loop verified.")
    return failed


if __name__ == "__main__":
    sys.exit(main())
