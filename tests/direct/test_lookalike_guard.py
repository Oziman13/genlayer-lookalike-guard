"""Lookalike Guard v0.1 tests (genlayer-test direct mode: in-memory, model mocked).

Run from the repository root:  python3 -m pytest tests/direct
"""

import json
import random
import re

import pytest
from gltest.direct import create_address

CONTRACT = "contracts/lookalike_guard.py"


def low(address):
    return "0x" + bytes(address).hex() if isinstance(address, (bytes, bytearray)) else str(address).lower()


def person(name):
    return create_address(name)


@pytest.fixture
def book(direct_vm, direct_deploy, direct_owner):
    direct_vm.sender = direct_owner
    return direct_deploy(CONTRACT)


def reg(c, vm, who, name):
    vm.sender = who
    return json.loads(c.register(name))


def verdict(confusing=False, target=0, shared=""):
    return json.dumps({"confusing": confusing, "target": target, "shared": shared})


def mock_name(vm, name, reply):
    vm.mock_llm("BEGIN NEW NAME ---\\n" + re.escape(name) + "\\n", reply)


def canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


ALICE, BOB, CARL = "alice", "bob", "carl"


# -- empty and basic -----------------------------------------------------------------------------------------------------------

def test_deploy_is_empty(book):
    assert book.get_name_count() == 0 and book.get_refusal_count() == 0
    assert json.loads(book.get_names_page(0, 10)) == {"items": [], "total": 0}
    assert json.loads(book.get_refusals_page(0, 10)) == {"items": [], "total": 0}
    assert book.get_name_json("nobody") == "NONE" and book.get_name_by_id_json(0) == "NONE"
    assert book.get_name_by_id_json(-1) == "NONE" and book.get_name_by_id_json("0") == "NONE"


def test_a_first_name_is_registered_without_the_model(book, direct_vm):
    out = reg(book, direct_vm, person(ALICE), "PayPal")
    assert out == {"status": "REGISTERED", "id": 0, "compared": 0}
    record = json.loads(book.get_name_json("PayPal"))
    assert record == {"id": 0, "name": "PayPal", "skeleton": "paypal", "owner": low(person(ALICE)), "status": "ACTIVE",
                      "check": "NO_NEIGHBOURS", "revoked_by": None}
    assert book.get_name_count() == 1


def test_lookup_ignores_letter_case_and_spaces_around(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "PayPal")
    assert json.loads(book.get_name_json("  PAYPAL "))["id"] == 0
    assert json.loads(book.get_name_json("paypal"))["name"] == "PayPal"
    assert book.get_name_json("paypa1") == "NONE"        # only the exact name (ignoring case) is found
    assert book.get_name_json("x") == "NONE" and book.get_name_json(5) == "NONE"


def test_far_apart_names_never_call_the_model(book, direct_vm):
    for i, name in enumerate(["paypal", "stripe", "orchard", "granite"]):
        assert reg(book, direct_vm, person(name), name) == {"status": "REGISTERED", "id": i, "compared": 0}
    assert book.get_refusal_count() == 0


# -- what a name may look like -------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("name", ["abc", "a" * 32, "a.b", "a-b_c", "x1y2z3", "Şırnak", "istanbul", "Ölçü_aleti", "école",
                                  "хор", "αβγδ"])
def test_valid_names(book, direct_vm, name):
    assert reg(book, direct_vm, person(ALICE), name)["status"] == "REGISTERED"
    assert json.loads(book.get_name_json(name))["name"] == name


@pytest.mark.parametrize("name", ["ab", "a" * 33, "", "   ", "1abc", "_abc", "-abc", ".abc", "abc_", "abc-", "abc.", "a__b",
                                  "a--b", "a._b", "has space", "bad@name", "tab\tname", "emoji😀name", "new\nline",
                                  "abc!", "a/b", 5, None])
def test_invalid_names(book, direct_vm, name):
    direct_vm.sender = person(ALICE)
    with direct_vm.expect_revert("invalid name"):
        book.register(name)
    assert book.get_name_count() == 0


def test_letters_outside_latin_cyrillic_greek_are_refused(book, direct_vm):
    direct_vm.sender = person(ALICE)
    for name in ["名前名前名", "ﬁrst", "ḃetter"]:
        with direct_vm.expect_revert("unsupported letters"):
            book.register(name)


def test_mixed_scripts_are_refused(book, direct_vm):
    direct_vm.sender = person(ALICE)
    for name in ["pаypal", "payраl", "αbcd", "ааα", "хopа1"]:
        with direct_vm.expect_revert("mixed scripts"):
            book.register(name)
    assert reg(book, direct_vm, person(ALICE), "paypal")["status"] == "REGISTERED"


def test_digits_and_separators_do_not_count_as_a_script(book, direct_vm):
    assert reg(book, direct_vm, person(ALICE), "хор-2_0")["status"] == "REGISTERED"


def test_the_same_name_cannot_be_taken_twice_in_any_letter_case(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "Orchard")
    direct_vm.sender = person(BOB)
    for name in ["Orchard", "orchard", "ORCHARD", " orchard "]:
        with direct_vm.expect_revert("that name is taken"):
            book.register(name)
    assert book.get_name_count() == 1


# -- plain-code lookalikes (no model) ------------------------------------------------------------------------------------------

CONFUSABLE = [
    ("paypal", "paypa1"), ("paypal", "PayPaI"), ("paypal", "pay-pal"), ("paypal", "pay_pal"), ("paypal", "p.a.y.p.a.l"),
    ("xop", "хор"), ("istanbul", "İstanbul"), ("istanbul", "ist4nbul"), ("istanbul", "ıstanbul"), ("sirnak", "Şırnak"),
    ("microsoft", "rnicrosoft"), ("word", "vvord"), ("google", "go0gle"), ("google", "g00gle"), ("seven", "s3ven"),
    ("beta", "b3ta"), ("tomato", "t0mat0"), ("eclair", "éclair"), ("lemon", "l3mon"), ("lemon", "Iemon"),
    ("open", "op3n"), ("coffee", "c0ffee")
]


@pytest.mark.parametrize("first,second", CONFUSABLE)
def test_a_name_with_the_same_skeleton_is_refused_without_the_model(book, direct_vm, first, second):
    assert reg(book, direct_vm, person(ALICE), first)["status"] == "REGISTERED"
    if second.lower() == first.lower():
        pytest.skip("identical spelling is the 'taken' case")
    out = reg(book, direct_vm, person(BOB), second)
    assert out["status"] == "BLOCKED" and out["kind"] == "CONFUSABLE"
    assert out["with"] == 0 and out["with_name"] == first and out["shared"] == json.loads(book.get_name_json(first))["skeleton"]
    assert book.get_name_count() == 1 and book.get_refusal_count() == 1


def test_a_cyrillic_copy_of_a_cyrillic_only_lookalike_is_refused(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "сор")             # Cyrillic с, о, р
    out = reg(book, direct_vm, person(BOB), "cop")         # Latin lookalike of the same word
    assert out["status"] == "BLOCKED" and out["kind"] == "CONFUSABLE"


def test_greek_lookalikes_are_folded(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "νοτε")             # Greek nu, omicron, tau, epsilon
    out = reg(book, direct_vm, person(BOB), "vote")
    assert out["status"] == "BLOCKED" and out["kind"] == "CONFUSABLE"


def test_the_refusal_is_logged_with_its_reason(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    reg(book, direct_vm, person(BOB), "paypa1")
    log = json.loads(book.get_refusals_page(0, 10))
    assert log["total"] == 1
    assert log["items"] == [{"n": 0, "name": "paypa1", "by": low(person(BOB)), "kind": "CONFUSABLE", "with": 0,
                             "with_name": "paypal", "shared": "paypal"}]


def test_a_released_name_stops_blocking_its_lookalikes(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    direct_vm.sender = person(ALICE)
    book.release("paypal")
    assert reg(book, direct_vm, person(BOB), "paypa1") == {"status": "REGISTERED", "id": 1, "compared": 0}
    assert reg(book, direct_vm, person(CARL), "payp4l")["status"] == "BLOCKED"       # now blocked by paypa1


def test_skeleton_is_in_the_record_and_separators_are_dropped(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "Wa-Ter.Mark")
    assert json.loads(book.get_name_json("wa-ter.mark"))["skeleton"] == "watermark"


# -- the model step -------------------------------------------------------------------------------------------------------------

def test_a_near_name_is_judged_by_the_model(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    mock_name(direct_vm, "paypall", verdict(True, 1, "paypal"))
    out = reg(book, direct_vm, person(BOB), "paypall")
    assert out == {"status": "BLOCKED", "kind": "SIMILAR", "with": 0, "with_name": "paypal", "shared": "paypal"}
    assert book.get_name_count() == 1
    assert json.loads(book.get_refusals_page(0, 5))["items"][0]["kind"] == "SIMILAR"


def test_a_near_name_the_model_clears_is_registered_with_a_note(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    mock_name(direct_vm, "paypath", verdict(False))
    assert reg(book, direct_vm, person(BOB), "paypath") == {"status": "REGISTERED", "id": 1, "compared": 1}
    assert json.loads(book.get_name_json("paypath"))["check"] == "CLEARED_AGAINST_1"


def test_two_edits_is_near_three_is_not(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "tomato")
    direct_vm.mock_llm("BEGIN NEW NAME", verdict(False))
    assert reg(book, direct_vm, person(BOB), "tomatxx")["compared"] == 1       # 2 edits
    assert reg(book, direct_vm, person(CARL), "tomatxyz")["compared"] == 1     # 3 edits from tomato, 2 from tomatxx
    out = reg(book, direct_vm, person("dave"), "orchardzzz")
    assert out["compared"] == 0


def test_the_shared_characters_may_be_written_in_any_letter_case_or_with_separators(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    mock_name(direct_vm, "paypall", verdict(True, 1, "PAY-PAL"))
    assert reg(book, direct_vm, person(BOB), "paypall")["shared"] == "paypal"


@pytest.mark.parametrize("reply", [
    "not json",
    "",
    json.dumps([]),
    json.dumps({"confusing": True, "target": 1}),
    json.dumps({"confusing": True, "target": 1, "shared": "paypal", "why": "x"}),
    json.dumps({"confusing": "yes", "target": 1, "shared": "paypal"}),
    json.dumps({"confusing": True, "target": 0, "shared": "paypal"}),
    json.dumps({"confusing": True, "target": 2, "shared": "paypal"}),
    json.dumps({"confusing": True, "target": -1, "shared": "paypal"}),
    json.dumps({"confusing": True, "target": True, "shared": "paypal"}),
    json.dumps({"confusing": True, "target": "1", "shared": "paypal"}),
    json.dumps({"confusing": True, "target": 1, "shared": "stripe"}),
    json.dumps({"confusing": True, "target": 1, "shared": "pa"}),
    json.dumps({"confusing": True, "target": 1, "shared": ""}),
    json.dumps({"confusing": True, "target": 1, "shared": 5}),
    json.dumps({"confusing": True, "target": 1, "shared": "paypall"}),
    json.dumps({"confusing": False, "target": 1, "shared": ""}),
    json.dumps({"confusing": False, "target": 0, "shared": "paypal"}),
    json.dumps({"confusing": None, "target": 0, "shared": ""}),
    "x" * 2001,
])
def test_a_badly_formed_model_answer_changes_nothing(book, direct_vm, reply):
    reg(book, direct_vm, person(ALICE), "paypal")
    direct_vm.clear_mocks()
    mock_name(direct_vm, "paypall", reply)
    direct_vm.sender = person(BOB)
    with direct_vm.expect_revert("could not be read"):
        book.register("paypall")
    assert book.get_name_count() == 1 and book.get_refusal_count() == 0
    assert book.get_name_json("paypall") == "NONE"


def test_no_model_answer_at_all_is_not_a_verdict(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    direct_vm.sender = person(BOB)
    with direct_vm.expect_revert("could not be read"):
        book.register("paypall")


def test_a_string_answer_with_valid_json_is_read(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    mock_name(direct_vm, "paypall", verdict(True, 1, "paypal"))
    assert reg(book, direct_vm, person(BOB), "paypall")["kind"] == "SIMILAR"


def test_candidates_are_the_five_closest_oldest_first(book, direct_vm):
    for i, name in enumerate(["tomatxx", "tomatq", "tomatw", "tomatv", "tomatk", "tomatz", "tomatb"]):
        direct_vm.clear_mocks()
        direct_vm.mock_llm("BEGIN NEW NAME", verdict(False))
        reg(book, direct_vm, person("u" + str(i)), name)
    direct_vm.clear_mocks()
    # for "tomato": distance 1 = q, w, v, k, z, b (ids 1-6), distance 2 = xx (id 0). The five closest, oldest first:
    # q w v k z. xx (distance 2) and b (the sixth at distance 1) are left out.
    direct_vm.mock_llm(r"1\. tomatq\n2\. tomatw\n3\. tomatv\n4\. tomatk\n5\. tomatz\n--- END EXISTING NAMES",
                       verdict(True, 5, "tomat"))
    out = reg(book, direct_vm, person("zed"), "tomato")
    assert out["kind"] == "SIMILAR" and out["with_name"] == "tomatz" and out["with"] == 5


def test_closer_names_come_before_older_ones(book, direct_vm):
    direct_vm.mock_llm("BEGIN NEW NAME", verdict(False))
    reg(book, direct_vm, person("a1"), "tomatxx")      # 2 edits from tomato, older
    reg(book, direct_vm, person("a2"), "tomatq")       # 1 edit, newer
    direct_vm.clear_mocks()
    direct_vm.mock_llm(r"1\. tomatq\n2\. tomatxx\n--- END EXISTING NAMES", verdict(True, 2, "tomat"))
    assert reg(book, direct_vm, person("a3"), "tomato")["with_name"] == "tomatxx"


def test_released_and_revoked_names_are_not_candidates(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    direct_vm.sender = person(ALICE)
    book.release("paypal")
    assert reg(book, direct_vm, person(BOB), "paypall")["compared"] == 0


def test_the_prompt_shows_the_new_name_and_the_existing_ones(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    direct_vm.mock_llm(r"BEGIN EXISTING NAMES ---\n1\. paypal\n--- END EXISTING NAMES ---\n--- BEGIN NEW NAME ---\npaypall\n--- END NEW NAME ---",
                       verdict(True, 1, "paypal"))
    assert reg(book, direct_vm, person(BOB), "paypall")["status"] == "BLOCKED"


# -- limits -------------------------------------------------------------------------------------------------------------------------

def code_name(i):
    letters = "bcdfghkp"
    digits = [i % 8, (i // 8) % 8, (i // 64) % 8]
    return "".join(letters[d] * 3 for d in digits)


def test_five_names_per_address(book, direct_vm):
    for i in range(5):
        assert reg(book, direct_vm, person(ALICE), code_name(i))["status"] == "REGISTERED"
    direct_vm.sender = person(ALICE)
    with direct_vm.expect_revert("too many names for one address"):
        book.register(code_name(5))
    assert reg(book, direct_vm, person(BOB), code_name(5))["status"] == "REGISTERED"
    direct_vm.sender = person(ALICE)
    book.release(code_name(0))
    assert reg(book, direct_vm, person(ALICE), code_name(6))["status"] == "REGISTERED"


def test_released_names_still_use_a_registry_slot(book, direct_vm):
    for i in range(300):
        assert reg(book, direct_vm, person("o%d" % (i // 5)), code_name(i))["status"] == "REGISTERED"
    direct_vm.sender = person("late")
    with direct_vm.expect_revert("the registry is full"):
        book.register("zzzqqq")
    direct_vm.sender = person("o0")
    book.release(code_name(0))
    direct_vm.sender = person("late")
    with direct_vm.expect_revert("the registry is full"):
        book.register("zzzqqq")
    assert book.get_name_count() == 300


def test_refusal_log_is_capped_but_calls_still_return(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    for _ in range(105):
        assert reg(book, direct_vm, person(BOB), "paypa1")["status"] == "BLOCKED"
    assert book.get_refusal_count() == 100
    assert json.loads(book.get_refusals_page(99, 50))["items"][0]["n"] == 99


# -- release -----------------------------------------------------------------------------------------------------------------------

def test_release_is_for_the_owner_only(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    direct_vm.sender = person(BOB)
    with direct_vm.expect_revert("only the owner can release a name"):
        book.release("paypal")
    with direct_vm.expect_revert("unknown name"):
        book.release("stripe")
    with direct_vm.expect_revert("invalid name"):
        book.release("x")
    direct_vm.sender = person(ALICE)
    assert json.loads(book.release("PAYPAL")) == {"status": "RELEASED", "id": 0}
    assert book.get_name_json("paypal") == "NONE"
    assert json.loads(book.get_name_by_id_json(0))["status"] == "RELEASED"
    with direct_vm.expect_revert("unknown name"):
        book.release("paypal")


def test_a_released_name_can_be_registered_again_by_anyone(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    direct_vm.sender = person(ALICE)
    book.release("paypal")
    assert reg(book, direct_vm, person(BOB), "paypal") == {"status": "REGISTERED", "id": 1, "compared": 0}
    assert json.loads(book.get_name_json("paypal"))["owner"] == low(person(BOB))
    assert json.loads(book.get_name_by_id_json(0))["status"] == "RELEASED"


# -- challenges --------------------------------------------------------------------------------------------------------------------

@pytest.fixture
def pair(book, direct_vm):
    """alice owns 'paypal' (id 0); bob owns 'paypall' (id 1), which the model wrongly let through."""
    reg(book, direct_vm, person(ALICE), "paypal")
    mock_name(direct_vm, "paypall", verdict(False))
    reg(book, direct_vm, person(BOB), "paypall")
    direct_vm.clear_mocks()
    return book


def challenge(c, vm, who, name, against):
    vm.sender = who
    return json.loads(c.challenge(name, against))


def test_an_upheld_challenge_revokes_the_newer_name(pair, direct_vm):
    mock_name(direct_vm, "paypall", verdict(True, 1, "paypal"))
    out = challenge(pair, direct_vm, person(ALICE), "paypall", "paypal")
    assert out == {"status": "UPHELD", "revoked": 1, "shared": "paypal"}
    assert pair.get_name_json("paypall") == "NONE"
    record = json.loads(pair.get_name_by_id_json(1))
    assert record["status"] == "REVOKED" and record["revoked_by"] == 0
    assert json.loads(pair.get_name_json("paypal"))["status"] == "ACTIVE"


def test_a_rejected_challenge_changes_nothing_and_cannot_be_repeated(pair, direct_vm):
    mock_name(direct_vm, "paypall", verdict(False))
    assert challenge(pair, direct_vm, person(ALICE), "paypall", "paypal") == {"status": "REJECTED"}
    assert json.loads(pair.get_name_json("paypall"))["status"] == "ACTIVE"
    direct_vm.clear_mocks()
    mock_name(direct_vm, "paypall", verdict(True, 1, "paypal"))
    direct_vm.sender = person(ALICE)
    with direct_vm.expect_revert("this pair was already challenged"):
        pair.challenge("paypall", "paypal")


def test_an_upheld_pair_cannot_be_challenged_again_even_after_the_name_returns(pair, direct_vm):
    mock_name(direct_vm, "paypall", verdict(True, 1, "paypal"))
    challenge(pair, direct_vm, person(ALICE), "paypall", "paypal")
    direct_vm.sender = person(ALICE)
    with direct_vm.expect_revert("unknown name"):
        pair.challenge("paypall", "paypal")


def test_a_revoked_name_can_be_registered_again_but_is_checked_again(pair, direct_vm):
    mock_name(direct_vm, "paypall", verdict(True, 1, "paypal"))
    challenge(pair, direct_vm, person(ALICE), "paypall", "paypal")
    assert reg(pair, direct_vm, person("carl"), "paypall")["status"] == "BLOCKED"


def test_only_the_owner_of_the_older_name_can_challenge(pair, direct_vm):
    mock_name(direct_vm, "paypall", verdict(True, 1, "paypal"))
    for who in (person(BOB), person(CARL)):
        direct_vm.sender = who
        with direct_vm.expect_revert("only the owner of the older name can challenge"):
            pair.challenge("paypall", "paypal")


def test_the_older_name_must_really_be_older(pair, direct_vm):
    mock_name(direct_vm, "paypal", verdict(True, 1, "paypal"))
    direct_vm.sender = person(BOB)
    with direct_vm.expect_revert("the challenged name is not newer"):
        pair.challenge("paypal", "paypall")


def test_you_cannot_challenge_your_own_name(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    mock_name(direct_vm, "paypall", verdict(False))
    reg(book, direct_vm, person(ALICE), "paypall")
    direct_vm.clear_mocks()
    direct_vm.sender = person(ALICE)
    with direct_vm.expect_revert("a name cannot be challenged by its own owner"):
        book.challenge("paypall", "paypal")


def test_unknown_or_inactive_names_cannot_be_challenged(pair, direct_vm):
    direct_vm.sender = person(ALICE)
    with direct_vm.expect_revert("unknown name"):
        pair.challenge("nothing", "paypal")
    with direct_vm.expect_revert("unknown name"):
        pair.challenge("paypall", "nothing")
    direct_vm.sender = person(BOB)
    pair.release("paypall")
    direct_vm.sender = person(ALICE)
    with direct_vm.expect_revert("unknown name"):
        pair.challenge("paypall", "paypal")


def test_names_too_far_apart_are_not_compared(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "orchard")
    mock_name(direct_vm, "orchardxxxx", verdict(False))
    # four edits away from "orchard" (not a model candidate: registered without a comparison)
    assert reg(book, direct_vm, person(BOB), "orchardxxxx")["compared"] == 0
    direct_vm.sender = person(ALICE)
    with direct_vm.expect_revert("the names are not close enough to compare"):
        book.challenge("orchardxxxx", "orchard")


def test_three_edits_is_still_close_enough_to_challenge(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "orchard")
    mock_name(direct_vm, "orchardxyz", verdict(False))
    reg(book, direct_vm, person(BOB), "orchardxyz")
    direct_vm.clear_mocks()
    mock_name(direct_vm, "orchardxyz", verdict(True, 1, "orchard"))
    assert challenge(book, direct_vm, person(ALICE), "orchardxyz", "orchard")["status"] == "UPHELD"


def test_an_unreadable_challenge_is_not_recorded(pair, direct_vm):
    mock_name(direct_vm, "paypall", "garbage")
    direct_vm.sender = person(ALICE)
    with direct_vm.expect_revert("could not be read"):
        pair.challenge("paypall", "paypal")
    direct_vm.clear_mocks()
    mock_name(direct_vm, "paypall", verdict(True, 1, "paypal"))
    assert challenge(pair, direct_vm, person(ALICE), "paypall", "paypal")["status"] == "UPHELD"


def test_the_challenge_asks_about_the_older_name_only(pair, direct_vm):
    direct_vm.mock_llm(r"BEGIN EXISTING NAMES ---\n1\. paypal\n--- END EXISTING NAMES ---\n--- BEGIN NEW NAME ---\npaypall\n",
                       verdict(True, 1, "paypal"))
    assert challenge(pair, direct_vm, person(ALICE), "paypall", "paypal")["status"] == "UPHELD"


def test_a_revoked_name_frees_its_owner_slot(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    mock_name(direct_vm, "paypall", verdict(False))
    for name in ["paypall"] + [code_name(i) for i in range(4)]:
        reg(book, direct_vm, person(BOB), name)
    direct_vm.sender = person(BOB)
    with direct_vm.expect_revert("too many names for one address"):
        book.register(code_name(4))
    direct_vm.clear_mocks()
    mock_name(direct_vm, "paypall", verdict(True, 1, "paypal"))
    challenge(book, direct_vm, person(ALICE), "paypall", "paypal")
    assert reg(book, direct_vm, person(BOB), code_name(4))["status"] == "REGISTERED"


# -- views ----------------------------------------------------------------------------------------------------------------------------

def test_check_json_is_a_dry_run(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    mock_name(direct_vm, "paypall", verdict(False))
    reg(book, direct_vm, person(BOB), "paypall")
    assert json.loads(book.check_json("paypa1")) == {"valid": True, "skeleton": "paypal", "taken": False,
                                                    "confusable_with": 0, "neighbours": [1]}
    assert json.loads(book.check_json("PAYPAL")) == {"valid": True, "skeleton": "paypal", "taken": True,
                                                    "confusable_with": 0, "neighbours": [1]}
    assert json.loads(book.check_json("orchard")) == {"valid": True, "skeleton": "orchard", "taken": False,
                                                     "confusable_with": None, "neighbours": []}
    assert json.loads(book.check_json("ab")) == {"valid": False, "error": "invalid name"}
    assert json.loads(book.check_json("pаypal")) == {"valid": False, "error": "mixed scripts"}
    assert json.loads(book.check_json(5)) == {"valid": False, "error": "invalid name"}
    assert book.get_name_count() == 2 and book.get_refusal_count() == 0


def test_names_page_and_owner_view(book, direct_vm):
    for i, name in enumerate(["paypal", "stripe", "orchard"]):
        reg(book, direct_vm, person(ALICE if i != 1 else BOB), name)
    page = json.loads(book.get_names_page(1, 2))
    assert page["total"] == 3 and [n["name"] for n in page["items"]] == ["stripe", "orchard"]
    assert json.loads(book.get_names_page(3, 5))["items"] == []
    assert [n["name"] for n in json.loads(book.get_owner_json(low(person(ALICE))))] == ["paypal", "orchard"]
    assert json.loads(book.get_owner_json(low(person("nobody")))) == []
    for bad in [(-1, 5), (0, 0), (0, 51), ("0", 5), (0, "5")]:
        with direct_vm.expect_revert("bad page"):
            book.get_names_page(*bad)
        with direct_vm.expect_revert("bad page"):
            book.get_refusals_page(*bad)
    with direct_vm.expect_revert("invalid address"):
        book.get_owner_json("alice")
    assert json.loads(book.get_names_page(0, 50))["total"] == 3


def test_address_in_owner_view_ignores_case(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    upper = "0x" + low(person(ALICE))[2:].upper()
    assert len(json.loads(book.get_owner_json(upper))) == 1


# -- the validators ------------------------------------------------------------------------------------------------------------------

NOT = {"state": "OK", "confusing": False}
HIT = {"state": "OK", "confusing": True, "target": 0, "shared": "paypal"}


def judged(book, direct_vm, reply):
    reg(book, direct_vm, person(ALICE), "paypal")
    direct_vm.clear_mocks()
    mock_name(direct_vm, "paypall", reply)
    direct_vm.sender = person(BOB)
    book.register("paypall")


def test_validator_accepts_the_same_verdict(book, direct_vm):
    judged(book, direct_vm, verdict(False))
    assert direct_vm.run_validator() is True


def test_validator_accepts_the_same_target_with_other_shared_characters(book, direct_vm):
    judged(book, direct_vm, verdict(True, 1, "paypal"))
    assert direct_vm.run_validator() is True
    other = {"state": "OK", "confusing": True, "target": 0, "shared": "payp"}
    assert direct_vm.run_validator(leader_result=canon(other)) is True


def test_validator_rejects_a_confusing_name_its_own_model_clears(book, direct_vm):
    judged(book, direct_vm, verdict(False))
    assert direct_vm.run_validator(leader_result=canon(HIT)) is False


def test_validator_rejects_a_missed_copy(book, direct_vm):
    judged(book, direct_vm, verdict(True, 1, "paypal"))
    assert direct_vm.run_validator(leader_result=canon(NOT)) is False


def test_validator_rejects_a_different_target(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    mock_name(direct_vm, "paypath", verdict(False))
    reg(book, direct_vm, person(BOB), "paypath")
    direct_vm.clear_mocks()
    mock_name(direct_vm, "paypall", verdict(True, 1, "paypal"))
    direct_vm.sender = person(CARL)
    book.register("paypall")
    assert direct_vm.run_validator() is True
    other = {"state": "OK", "confusing": True, "target": 1, "shared": "payp"}
    assert direct_vm.run_validator(leader_result=canon(other)) is False


@pytest.mark.parametrize("forged", [
    {"state": "OK", "confusing": True, "target": 0, "shared": "stripe"},          # not in either name
    {"state": "OK", "confusing": True, "target": 0, "shared": "pa"},              # too short
    {"state": "OK", "confusing": True, "target": 0, "shared": "paypall"},         # not in the older name
    {"state": "OK", "confusing": True, "target": 0, "shared": "PAYPAL"},          # not canonical (skeleton is lower case)
    {"state": "OK", "confusing": True, "target": 1, "shared": "paypal"},          # no such candidate
    {"state": "OK", "confusing": True, "target": -1, "shared": "paypal"},
    {"state": "OK", "confusing": True, "target": 0},
    {"state": "OK", "confusing": True, "target": 0, "shared": ""},
    {"state": "OK", "confusing": False, "target": 0, "shared": ""},
    {"state": "OK", "confusing": "yes"},
    {"state": "MAYBE"},
    {"confusing": True, "target": 0, "shared": "paypal"},
    [],
])
def test_validator_rejects_forged_readings(book, direct_vm, forged):
    judged(book, direct_vm, verdict(True, 1, "paypal"))
    assert direct_vm.run_validator(leader_result=canon(forged)) is False


def test_validator_rejects_text_that_is_not_the_canonical_json(book, direct_vm):
    judged(book, direct_vm, verdict(False))
    assert direct_vm.run_validator(leader_result=json.dumps(NOT, indent=2)) is False
    assert direct_vm.run_validator(leader_result="not json") is False
    assert direct_vm.run_validator(leader_result=5) is False
    assert direct_vm.run_validator(leader_result="x" * 2001) is False


def test_validator_rejects_an_error_when_it_can_read(book, direct_vm):
    judged(book, direct_vm, verdict(False))
    assert direct_vm.run_validator(leader_result=canon({"state": "ERROR"})) is False


def test_validator_rejects_a_reading_when_its_own_model_fails(book, direct_vm):
    judged(book, direct_vm, verdict(False))
    direct_vm.clear_mocks()
    mock_name(direct_vm, "paypall", "garbage")
    assert direct_vm.run_validator() is False


def test_validator_accepts_error_when_it_cannot_read_either(book, direct_vm):
    judged(book, direct_vm, verdict(False))
    direct_vm.clear_mocks()
    mock_name(direct_vm, "paypall", "garbage")
    assert direct_vm.run_validator(leader_result=canon({"state": "ERROR"})) is True


def test_the_challenge_uses_the_same_validator_rules(pair, direct_vm):
    mock_name(direct_vm, "paypall", verdict(True, 1, "paypal"))
    challenge(pair, direct_vm, person(ALICE), "paypall", "paypal")
    assert direct_vm.run_validator() is True
    assert direct_vm.run_validator(leader_result=canon(NOT)) is False


# -- independent checks of the skeleton -------------------------------------------------------------------------------------------

LATIN_VARIANTS = {"o": ["0", "O"], "a": ["4", "A", "á", "ä"], "e": ["3", "E", "é", "ë"], "s": ["5", "ş", "S"],
                  "t": ["7", "T"], "b": ["8", "B"], "i": ["1", "l", "I", "ı", "İ", "í"], "l": ["1", "I", "i", "L"],
                  "u": ["ü", "ú", "U"], "c": ["ç", "C"], "g": ["ğ", "G"], "n": ["ñ", "N"]}
CYRILLIC_FOR = {"a": "а", "e": "е", "o": "о", "p": "р", "c": "с", "y": "у", "x": "х"}


def skeleton_of(book, name):
    return json.loads(book.check_json(name))["skeleton"]


@pytest.mark.parametrize("seed", range(12))
def test_random_latin_disguises_keep_the_skeleton(book, direct_vm, seed):
    rnd = random.Random(seed)
    alphabet = "aeiolstcnubg"
    for _ in range(25):
        base = "".join(rnd.choice(alphabet) for _ in range(rnd.randint(4, 9)))
        if "rn" in base or "vv" in base:
            continue
        disguised = ""
        for ch in base:
            options = LATIN_VARIANTS.get(ch, []) + [ch]
            disguised += rnd.choice(options)
            if rnd.random() < 0.15:
                disguised += rnd.choice("-_.")
        disguised = disguised.rstrip("-_.")
        if not disguised[0].isalpha():
            disguised = base[0] + disguised[1:]
        assert skeleton_of(book, disguised) == skeleton_of(book, base), (base, disguised)


@pytest.mark.parametrize("seed", range(6))
def test_random_cyrillic_disguises_keep_the_skeleton(book, direct_vm, seed):
    rnd = random.Random(100 + seed)
    for _ in range(25):
        base = "".join(rnd.choice("aeopcyx") for _ in range(rnd.randint(3, 8)))
        if "rn" in base:
            continue
        assert skeleton_of(book, "".join(CYRILLIC_FOR[c] for c in base)) == skeleton_of(book, base)


@pytest.mark.parametrize("name", ["paypal", "Şırnak", "ist4nbul", "хор", "a_b-c.d", "go0gle", "rnicrosoft"])
def test_the_skeleton_of_a_skeleton_is_itself(book, name):
    first = skeleton_of(book, name)
    assert re.fullmatch(r"[a-z0-9]+", first) and "i" not in first
    assert skeleton_of(book, first) == first


def ref_distance(a, b):
    rows = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        rows[i][0] = i
    for j in range(len(b) + 1):
        rows[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            rows[i][j] = min(rows[i - 1][j] + 1, rows[i][j - 1] + 1, rows[i - 1][j - 1] + (a[i - 1] != b[j - 1]))
    return rows[len(a)][len(b)]


@pytest.mark.parametrize("seed", range(10))
def test_random_registries_follow_the_reference(book, direct_vm, seed):
    """Names drawn from a small alphabet so that many are near each other; the model clears everything."""
    rnd = random.Random(500 + seed)
    direct_vm.mock_llm("BEGIN NEW NAME", verdict(False))
    active = {}
    for n in range(40):
        name = "".join(rnd.choice("kmtzqdw") for _ in range(rnd.randint(3, 5)))
        direct_vm.sender = person("w%d" % n)
        key = name.lower()
        if key in active:
            with direct_vm.expect_revert("that name is taken"):
                book.register(name)
            continue
        skeleton = name
        near = sorted((ref_distance(skeleton, other), idx) for idx, other in active.items() if other != skeleton
                      and ref_distance(skeleton, other) <= 2)
        out = json.loads(book.register(name))
        assert out["status"] == "REGISTERED" and out["id"] == len(active)
        assert out["compared"] == min(5, len(near)), (name, near)
        active[out["id"]] = skeleton
    assert book.get_name_count() == len(active)


# -- every folded letter, from a written-out table (the specification) ----------------------------------------------------------------

CYRILLIC_TABLE = {"а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "l", "ј": "j", "ѕ": "s",
                  "һ": "h", "ԁ": "d", "ԛ": "q", "ԝ": "w", "к": "k", "м": "m", "н": "h", "т": "t", "в": "b", "ѵ": "v"}
GREEK_TABLE = {"α": "a", "ο": "o", "ν": "v", "ρ": "p", "ι": "l", "κ": "k", "τ": "t", "υ": "u", "χ": "x", "ε": "e",
               "β": "b", "η": "n", "ω": "w"}
LATIN_TABLE = {"ı": "l", "i": "l", "l": "l", "ç": "c", "ğ": "g", "ş": "s", "ö": "o", "ü": "u", "â": "a", "î": "l", "û": "u",
               "é": "e", "è": "e", "ê": "e", "ë": "e", "á": "a", "à": "a", "ä": "a", "ó": "o", "ò": "o", "ô": "o", "ú": "u",
               "ù": "u", "í": "l", "ì": "l", "ï": "l", "ñ": "n", "å": "a", "ø": "o", "ß": "ss", "æ": "ae", "œ": "oe",
               "İ": "l", "I": "l"}
DIGIT_TABLE = {"0": "o", "1": "l", "3": "e", "4": "a", "5": "s", "7": "t", "8": "b", "2": "2", "6": "6", "9": "9"}


@pytest.mark.parametrize("letter,expected", sorted(CYRILLIC_TABLE.items()))
def test_every_cyrillic_lookalike_folds_to_its_latin_letter(book, letter, expected):
    assert skeleton_of(book, "ааа" + letter) == "aaa" + expected


@pytest.mark.parametrize("letter,expected", sorted(GREEK_TABLE.items()))
def test_every_greek_lookalike_folds_to_its_latin_letter(book, letter, expected):
    assert skeleton_of(book, "ααα" + letter) == "aaa" + expected


@pytest.mark.parametrize("letter,expected", sorted(LATIN_TABLE.items()))
def test_every_latin_accent_folds_to_its_base_letter(book, letter, expected):
    assert skeleton_of(book, "ttt" + letter) == "ttt" + expected


@pytest.mark.parametrize("digit,expected", sorted(DIGIT_TABLE.items()))
def test_every_digit_that_passes_for_a_letter_folds(book, digit, expected):
    assert skeleton_of(book, "ttt" + digit) == "ttt" + expected


def test_digraphs_fold_and_plain_letters_stay(book):
    assert skeleton_of(book, "rnrnvvx") == "mmwx"
    assert skeleton_of(book, "abcdefghjkmnopqrstuvwxyz") == "abcdefghjkmnopqrstuvwxyz".replace("i", "l")
    assert skeleton_of(book, "abrnc") == "abmc" and skeleton_of(book, "abvc") == "abvc" and skeleton_of(book, "arc") == "arc"


# -- boundaries found by the mutation check ----------------------------------------------------------------------------------------------

def test_three_shared_characters_are_enough_and_two_are_not(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    mock_name(direct_vm, "paypall", verdict(True, 1, "pay"))
    assert reg(book, direct_vm, person(BOB), "paypall")["shared"] == "pay"


def test_shared_characters_must_be_in_the_new_name_too(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    mock_name(direct_vm, "paypath", verdict(True, 1, "paypal"))       # "paypal" is in the old name, not in "paypath"
    direct_vm.sender = person(BOB)
    with direct_vm.expect_revert("could not be read"):
        book.register("paypath")
    direct_vm.clear_mocks()
    mock_name(direct_vm, "paypath", verdict(True, 1, "payp"))         # "payp" is in both
    assert reg(book, direct_vm, person(BOB), "paypath")["shared"] == "payp"


def test_validator_checks_that_shared_characters_are_in_the_new_name(book, direct_vm):
    reg(book, direct_vm, person(ALICE), "paypal")
    mock_name(direct_vm, "paypath", verdict(True, 1, "payp"))
    reg(book, direct_vm, person(BOB), "paypath")
    assert direct_vm.run_validator() is True
    forged = {"state": "OK", "confusing": True, "target": 0, "shared": "paypal"}
    assert direct_vm.run_validator(leader_result=canon(forged)) is False


def test_validator_rejects_extra_keys_on_a_clear_reading(book, direct_vm):
    judged(book, direct_vm, verdict(False))
    assert direct_vm.run_validator(leader_result=canon({"state": "OK", "confusing": False, "target": 0})) is False
    assert direct_vm.run_validator(leader_result=canon({"state": "OK", "confusing": False, "extra": 1})) is False


@pytest.mark.parametrize("name", ["Àbc", "ɏbb", "Ѐаа", "ԯԯԯ", "Ͱαα", "ϿϿϿ"])
def test_letters_at_the_edges_of_the_three_alphabets_are_accepted(book, direct_vm, name):
    assert reg(book, direct_vm, person(ALICE), name)["status"] == "REGISTERED"


@pytest.mark.parametrize("name", ["ɐbb", "ԱԱԱ", "ʰbb"])
def test_letters_just_outside_the_alphabets_are_refused(book, direct_vm, name):
    direct_vm.sender = person(ALICE)
    with direct_vm.expect_revert("unsupported letters"):
        book.register(name)
