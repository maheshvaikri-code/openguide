"""The message an agent receives (docs/briefs/arch-drift-harness.md, AC 5): the same in Arm A and Arm B."""
import pytest

from archstudy import feedback, rules


def v(rule, path="app/handlers/orders.py", line=3, msg="something is wrong"):
    return rules.Violation(path, line, rule, msg)


def test_no_violations_means_no_message():
    assert feedback.render([]) == ""


def test_the_message_names_rule_location_and_carries_the_adr_text():
    msg = feedback.render([v("V2", line=7, msg="redis is imported outside app/cache.py; see ADR-002")])
    assert "V2" in msg and "app/handlers/orders.py:7" in msg
    assert "redis is imported outside app/cache.py" in msg
    assert rules.adr_text("V2").splitlines()[0] in msg


def test_the_message_does_not_depend_on_the_order_the_violations_arrive_in():
    a, b = v("V1", line=1), v("V2", line=2)
    assert feedback.render([a, b]) == feedback.render([b, a])


def test_the_same_violations_give_a_byte_identical_message():
    vs = [v("V1", line=1), v("V3", "app/services/x.py", 9)]
    assert feedback.render(vs).encode() == feedback.render(list(vs)).encode()


def test_each_rule_text_appears_once_however_many_violations_it_has():
    msg = feedback.render([v("V2", line=n) for n in range(1, 6)])
    assert msg.count(rules.adr_text("V2").splitlines()[0]) == 1


def test_the_message_is_bounded_however_many_violations_there_are():
    msg = feedback.render([v(r, f"app/handlers/f{i}.py", i) for i in range(200) for r in rules.VISIBLE])
    assert len(msg) <= feedback.MAX_CHARS
    assert "more" in msg                                    # says that it left some out


def test_a_held_out_rule_can_never_be_rendered():
    with pytest.raises(ValueError):
        feedback.render([v("H1")])
    with pytest.raises(ValueError):
        feedback.render([v("V1"), v("H3")])


def test_the_message_never_mentions_a_held_out_rule_or_its_adr():
    msg = feedback.render([v(r) for r in rules.VISIBLE])
    for rule in rules.HELD_OUT:
        assert rules.adr_text(rule).splitlines()[0] not in msg
