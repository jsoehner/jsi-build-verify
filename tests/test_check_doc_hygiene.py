from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
from check_doc_hygiene import check_file, main


def test_sanitizes_pqc_key_exchange_gitleaks_false_positive(tmp_path: Path) -> None:
    doc = tmp_path / "BUILD_VERIFICATION.md"
    doc.write_text(
        '| `GET` | `/api/crypto/pqc-status` | `200` | `tlsKeyExchange: "X25519MLKEM768"` |\n',
        encoding="utf-8",
    )
    errors, rewritten = check_file(doc, fix=True)
    assert errors == []
    assert rewritten == 1
    assert 'tlsKeyExchange: "X25519MLKEM768"' not in doc.read_text(encoding="utf-8")
    assert "tlsKeyExchange (X25519MLKEM768)" in doc.read_text(encoding="utf-8")


def test_blocks_real_api_keys_and_private_keys(tmp_path: Path) -> None:
    doc = tmp_path / "BUILD_VERIFICATION.md"
    doc.write_text(
        "Leaked key: AIzaSy0123456789abcdefghij0123456789abc\n",
        encoding="utf-8",
    )
    assert main([str(doc), "--fix"]) == 1


def test_leaves_clean_markdown_untouched(tmp_path: Path) -> None:
    doc = tmp_path / "BUILD_VERIFICATION.md"
    original = "# Build Verification\n\n- TLS hybrid PQC key exchange (X25519MLKEM768) verified.\n"
    doc.write_text(original, encoding="utf-8")
    errors, rewritten = check_file(doc, fix=True)
    assert errors == []
    assert rewritten == 0
    assert doc.read_text(encoding="utf-8") == original
