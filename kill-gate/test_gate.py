"""Guardrail tests. Run with: python3 test_gate.py"""
from gate import kill, load_scores, ship, total


def calls(*sums):
    """Judge calls whose three axes add to each given sum, craft carrying the remainder."""
    return [{"craft": s - 8, "message": 4, "warmth": 4} for s in sums]


def test_same_scores_same_kill():
    s = {"a": calls(15, 16), "b": calls(12, 13), "c": calls(17, 17)}
    assert kill(s) == kill(dict(reversed(list(s.items())))) == "b"


def test_refuses_fewer_than_three_renders():
    # Hardcoded, not range(MIN_CLIPS): a test that follows the constant it guards passes
    # vacuously when the constant is lowered, which is the exact break it exists to catch.
    for n in (0, 1, 2):
        s = {chr(97 + i): calls(15) for i in range(n)}
        try:
            kill(s)
        except ValueError as e:
            assert "picking" in str(e)
        else:
            raise AssertionError(f"accepted {n} renders")


def test_kills_exactly_one_and_ships_the_rest_in_order():
    s = {"z": calls(16), "y": calls(10), "x": calls(14), "w": calls(15)}
    assert kill(s) == "y"
    assert ship(s) == ["z", "x", "w"]


def test_tie_breaks_on_name_not_on_order():
    s1 = {"b": calls(12), "a": calls(12), "c": calls(15)}
    s2 = {"a": calls(12), "b": calls(12), "c": calls(15)}
    assert kill(s1) == kill(s2) == "a"


def test_missing_axis_fails_loud():
    try:
        total([{"craft": 5, "message": 5}])
    except ValueError as e:
        assert "warmth" in str(e)
    else:
        raise AssertionError("scored a call with a missing axis")


def test_rejects_nan_and_out_of_range():
    for bad in (float("nan"), float("inf"), -1, 0, 11, 100):
        try:
            total([{"craft": bad, "message": 5, "warmth": 5}])
        except ValueError as e:
            assert "range" in str(e)
        else:
            raise AssertionError(f"accepted a score of {bad}")


def test_boolean_is_not_a_score():
    try:
        total([{"craft": True, "message": 5, "warmth": 5}])
    except ValueError as e:
        assert "boolean" in str(e)
    else:
        raise AssertionError("float(True) became a score of 1.0")


def test_duplicate_render_names_refused():
    try:
        load_scores('{"a": [{"craft":3,"message":3,"warmth":3}], "a": [{"craft":9,"message":9,"warmth":9}], "b": [], "c": []}')
    except ValueError as e:
        assert "twice" in str(e)
    else:
        raise AssertionError("two renders named a were merged into one")


def test_more_calls_change_the_mean_not_the_rule():
    one = {"a": calls(14), "b": calls(13), "c": calls(15)}
    many = {"a": calls(14, 14, 14), "b": calls(12, 13, 14), "c": calls(15, 15, 15)}
    assert kill(one) == kill(many) == "b"
    assert total(many["b"]) == 13.0


def test_judge_reply_must_be_exactly_one_object():
    from judge import parse_scores

    good = {"craft": 6.0, "message": 5.0, "warmth": 4.0}
    assert parse_scores('{"craft":6,"message":5,"warmth":4,"why":"fine"}') == good
    assert parse_scores('```json\n{"craft":6,"message":5,"warmth":4}\n```') == good
    for bad in (
        '{"draft":{"craft":6,"message":5,"warmth":4}',  # truncated, outer brace missing
        '{"craft":6,"message":5,"warmth":4}\nCorrection: {"craft":1,"message":1,"warmth":1}',
        '{"draft":{"craft":6,"message":5,"warmth":4}}',  # axes not at the top level
        'Scores: {"craft":6,"message":5,"warmth":4}',  # prose before the object
        '{"craft":6,"message":5,"warmth":4,"craft":1}',  # a key named twice
        '[{"craft":6,"message":5,"warmth":4}]',  # a list, not an object
        '{"craft":6,"message":5,"warmth":4,"why":NaN}',  # NaN is not JSON
        '{"craft":6,"message":5,"warmth":4,"why":Infinity}',  # nor is Infinity
        '{"craft":"6","message":5,"warmth":4}',  # a quoted number is a string
    ):
        try:
            parse_scores(bad)
        except ValueError:
            continue
        raise AssertionError(f"accepted a malformed judge reply: {bad!r}")


def test_string_is_not_a_score():
    for bad in ("6", "six", [6], None):
        try:
            total([{"craft": bad, "message": 5, "warmth": 5}])
        except ValueError as e:
            assert "non-number" in str(e)
        else:
            raise AssertionError(f"accepted {bad!r} as a score")


if __name__ == "__main__":
    import sys

    wanted = sys.argv[1:]  # e.g. python3 test_gate.py tie  (substring match, blank runs all)
    ran = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_") and (not wanted or any(w in name for w in wanted)):
            fn()
            print("ok", name)
            ran += 1
    if not ran:
        print(f"no test matched {wanted}", file=sys.stderr)
        sys.exit(1)
