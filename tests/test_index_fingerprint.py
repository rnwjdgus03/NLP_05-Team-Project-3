"""인덱스 지문 — '같은 인덱스인가'를 사후에 확인한다 (2026-08-02).

실측: 같은 메타 파일로 Chroma 인덱스를 재빌드했더니 골드 recall 이 흔들렸다.
      table@1 0.833 -> 0.750, item@1 0.917 -> 0.833, obj@1 0.667 -> 0.750.
      manifest 의 source_meta_sha256 과 document_count 는 양쪽 다 같아서
      '인덱스가 정말 같은가'를 확인할 방법이 없었다.

같은 인덱스를 고정하면 검색은 결정적이다(후보 CSV 해시가 바이트 단위로 일치).
따라서 A/B 비교에서는 인덱스를 재빌드하지 않는 것이 규칙이고,
지문은 그 규칙이 지켜졌는지 검사하는 수단이다.
"""
import numpy as np

from kosis_build_chroma_meta_index import embedding_fingerprint


def test_same_input_gives_the_same_fingerprint():
    ids = ["c1", "c2"]
    vectors = [np.array([0.1, 0.2], dtype=np.float32),
               np.array([0.3, 0.4], dtype=np.float32)]
    assert embedding_fingerprint(ids, vectors) == embedding_fingerprint(ids, vectors)


def test_order_does_not_matter():
    """upsert 순서가 달라도 같은 인덱스면 같은 지문이어야 한다."""
    a = embedding_fingerprint(["c1", "c2"],
                              [np.array([0.1], dtype=np.float32),
                               np.array([0.2], dtype=np.float32)])
    b = embedding_fingerprint(["c2", "c1"],
                              [np.array([0.2], dtype=np.float32),
                               np.array([0.1], dtype=np.float32)])
    assert a == b


def test_changed_vector_changes_both_fingerprints():
    base = embedding_fingerprint(["c1"], [np.array([0.1], dtype=np.float32)])
    other = embedding_fingerprint(["c1"], [np.array([0.9], dtype=np.float32)])
    assert base[0] != other[0]
    assert base[1] != other[1]


def test_floating_point_noise_moves_only_the_raw_fingerprint():
    """이 구분이 핵심이다.

    원본만 다르고 반올림이 같으면 부동소수점 오차 — 좌표는 사실상 같다.
    둘 다 다르면 입력이나 모델이 실제로 바뀐 것이다.
    """
    base = embedding_fingerprint(["c1"], [np.array([0.100000001], dtype=np.float32)])
    noisy = embedding_fingerprint(["c1"], [np.array([0.100000045], dtype=np.float32)])
    assert base[0] != noisy[0]
    assert base[1] == noisy[1]


def test_changed_id_changes_the_fingerprint():
    a = embedding_fingerprint(["c1"], [np.array([0.1], dtype=np.float32)])
    b = embedding_fingerprint(["c2"], [np.array([0.1], dtype=np.float32)])
    assert a != b


def test_document_count_alone_cannot_detect_a_change():
    """왜 지문이 필요한지 — 문서 수는 같아도 인덱스는 다를 수 있다."""
    a = embedding_fingerprint(["c1", "c2"],
                              [np.array([0.1], dtype=np.float32),
                               np.array([0.2], dtype=np.float32)])
    b = embedding_fingerprint(["c1", "c2"],
                              [np.array([0.1], dtype=np.float32),
                               np.array([0.7], dtype=np.float32)])
    assert a != b


def test_fingerprints_are_short_enough_to_eyeball():
    raw, rounded = embedding_fingerprint(["c1"], [np.array([0.1], dtype=np.float32)])
    assert len(raw) == 32 and len(rounded) == 32


def test_empty_index_does_not_raise():
    assert len(embedding_fingerprint([], [])[0]) == 32
