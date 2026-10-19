from pygrader.proposals import normalize_points


def test_scale_down_overflow():
    # 合計130 → 100 に正規化
    result = normalize_points([70, 30, 30], 100)
    assert sum(result) == 100
    assert all(p >= 1 for p in result)
    assert result[0] > result[1]  # 比率はおおむね維持


def test_scale_up():
    result = normalize_points([5, 3, 2], 100)
    assert sum(result) == 100
    assert result == [50, 30, 20]


def test_already_exact():
    assert normalize_points([70, 20, 10], 100) == [70, 20, 10]


def test_rounding_remainder_assigned():
    # 3等分できない合計でも厳密に一致する
    result = normalize_points([1, 1, 1], 100)
    assert sum(result) == 100


def test_zero_points():
    result = normalize_points([0, 0], 50)
    assert sum(result) == 50


def test_empty():
    assert normalize_points([], 100) == []
