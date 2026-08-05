"""씨앗 좌표 사전 파싱 (2026-08-05).

원본은 `Dayoooun/korea-stats-mcp` 의 `src/data/quickStatsParams.ts` (MIT).
아래 픽스처는 그 파일에서 **그대로 떼어온 조각**이다. 모양이 바뀌면 여기서 깨진다.

파싱에서 실제로 걸리는 것은 **주석**이다:

    objL1: '00',          // 전국 (C1: "00")
    itemId: 'T20',        // 총인구수 (ITM_ID: "T20")

주석 안에 따옴표가 있어서 그냥 정규식을 돌리면 필드가 어긋난다.
`DictWriter(extrasaction='ignore')` 로 520개 표를 헛수집한 게 오늘 아침이다 —
**조용한 실패는 정상처럼 보인다.** 그래서 파서는 개수와 값을 함께 잰다.
"""
import textwrap

import pytest

from build_seed_coordinates import parse_entries, parse_regions

FIXTURE = textwrap.dedent("""\
    /** 인구동향/출산율/혼인율 등에서 사용하는 지역 코드 */
    export const REGION_CODES_DEMOGRAPHIC: Record<string, string> = {
      '전국': '00',
      '서울': '11',
      '부산': '21',
    };

    /** 인구(주민등록)에서 사용하는 지역 코드 */
    export const REGION_CODES_POPULATION: Record<string, string> = {
      '전국': '00',
      '서울': '11',
      '부산': '26',
    };

    export const QUICK_STATS_PARAMS: Record<string, QuickStatsParam> = {
      // ===== 인구 관련 =====
      // DT_1B040A3: 행정구역(시군구)별 성별 인구수 (1992~2025, 최신 데이터)
      '인구': {
        orgId: '101',
        tableId: 'DT_1B040A3',
        tableName: '행정구역(시군구)별 성별 인구수',
        description: '주민등록 총인구',
        objL1: '00',          // 전국 (C1: "00")
        itemId: 'T20',        // 총인구수 (ITM_ID: "T20")
        unit: '명',
        regionCodes: REGION_CODES_POPULATION,
      },
      '실업률': {
        orgId: '101',
        tableId: 'DT_1DA7004S',
        tableName: '행정구역(시도)별 경제활동인구',
        description: '실업률',
        objL1: '00',          // 전국 (OBJ_ID: "A")
        itemId: 'T80',        // 실업률 (%)
        unit: '%',
        regionCodes: REGION_CODES_DEMOGRAPHIC,
        supportedPeriods: ['Y', 'Q', 'M'],
      },
      '물가': {
        orgId: '101',
        tableId: 'DT_1J22001',
        tableName: '지출목적별 소비자물가지수',
        description: '소비자물가지수',
        objL1: 'T10',
        objL2: '0',           // 총지수
        itemId: 'T',
        unit: '2020=100',
        supportedPeriods: ['Y', 'M'],
      },
    };
    """)


@pytest.fixture
def rows():
    return {row["keyword"]: row for row in parse_entries(FIXTURE)}


# --------------------------------------------------------------------------
# 좌표를 온전히 읽는가
# --------------------------------------------------------------------------

def test_every_entry_is_found(rows):
    assert set(rows) == {"인구", "실업률", "물가"}


def test_a_full_coordinate(rows):
    row = rows["인구"]
    assert row["org_id"] == "101"
    assert row["tbl_id"] == "DT_1B040A3"
    assert row["itm_id"] == "T20"
    assert row["obj_l1"] == "00"
    assert row["unit"] == "명"


def test_comments_do_not_leak_into_fields(rows):
    """`// 총인구수 (ITM_ID: "T20")` 의 따옴표가 필드로 새면 안 된다."""
    for row in rows.values():
        for value in row.values():
            assert "//" not in str(value)
            assert "ITM_ID" not in str(value)


def test_the_second_axis_is_kept(rows):
    """objL2 를 빠뜨리면 KOSIS 가 err:20 을 준다 — '데이터 없음'이 아니다.

    오늘 프로브에서 정확히 이걸 밟았다. 축 0개로 조회해놓고
    '어느 기간에도 값이 없다'고 28건을 좌표 오류로 셀 뻔했다.
    """
    assert rows["물가"]["obj_l2"] == "0"
    assert rows["인구"]["obj_l2"] == ""


def test_periods_are_read(rows):
    assert rows["실업률"]["prd_se_list"] == "Y|Q|M"
    assert rows["물가"]["prd_se_list"] == "Y|M"


def test_missing_periods_default_to_annual(rows):
    """원본이 `supportedPeriods` 를 생략하면 연간이다(인터페이스 주석에 그렇게 쓰여 있다)."""
    assert rows["인구"]["prd_se_list"] == "Y"


def test_the_region_scheme_is_recorded(rows):
    assert rows["인구"]["region_scheme"] == "REGION_CODES_POPULATION"
    assert rows["실업률"]["region_scheme"] == "REGION_CODES_DEMOGRAPHIC"
    assert rows["물가"]["region_scheme"] == ""


def test_provenance_is_stamped(rows):
    """어디서 왔는지 잃으면 우리 후보와 섞였을 때 독립성을 증명할 수 없다."""
    assert all(row["source"] == "korea-stats-mcp" for row in rows.values())


# --------------------------------------------------------------------------
# 지역 코드 — 표마다 다르다는 것이 요점이다
# --------------------------------------------------------------------------

def test_region_schemes_are_separate():
    regions = parse_regions(FIXTURE)
    by_scheme = {}
    for row in regions:
        by_scheme.setdefault(row["scheme"], {})[row["region"]] = row["code"]
    assert set(by_scheme) == {"REGION_CODES_DEMOGRAPHIC", "REGION_CODES_POPULATION"}


def test_the_same_city_has_different_codes():
    """**이게 이 사전을 가져오는 이유다.**

    부산이 인구동향에서는 21, 주민등록에서는 26 이다.
    표를 맞히고도 축 값을 틀리면 조용히 다른 값이 온다.
    """
    regions = parse_regions(FIXTURE)
    busan = {row["scheme"]: row["code"] for row in regions if row["region"] == "부산"}
    assert busan["REGION_CODES_DEMOGRAPHIC"] == "21"
    assert busan["REGION_CODES_POPULATION"] == "26"


# --------------------------------------------------------------------------
# 원본 구조가 바뀌면 조용히 실패하지 않는다
# --------------------------------------------------------------------------

def test_a_missing_block_raises():
    with pytest.raises(SystemExit):
        parse_entries("export const SOMETHING_ELSE = {};")


def test_entries_without_a_table_are_dropped():
    broken = "export const QUICK_STATS_PARAMS = {\n  '없음': {\n    orgId: '101',\n  },\n};"
    assert parse_entries(broken) == []
