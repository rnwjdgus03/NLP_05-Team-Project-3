from kosis_verify_claim_values import exact_api_coordinate_rows


def request():
    return {
        "orgId": "101", "tblId": "T1", "itmId": "I1", "prdSe": "M",
        "objL1": "A01", "objL2": "B02",
    }


def row(**overrides):
    value = {
        "ORG_ID": "101", "TBL_ID": "T1", "ITM_ID": "I1", "PRD_SE": "M",
        "C1": "A01", "C2": "B02", "PRD_DE": "202501", "DT": "10",
    }
    value.update(overrides)
    return value


def test_api_response_must_echo_item_and_all_axes():
    assert exact_api_coordinate_rows([row()], request()) == [row()]
    assert exact_api_coordinate_rows([row(ITM_ID="I2")], request()) == []
    assert exact_api_coordinate_rows([row(C2="B03")], request()) == []
    assert exact_api_coordinate_rows([row(PRD_SE="Q")], request()) == []


def test_api_response_missing_axis_is_not_exact():
    candidate = row()
    candidate.pop("C2")
    assert exact_api_coordinate_rows([candidate], request()) == []
