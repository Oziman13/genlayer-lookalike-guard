"""Lookalike Guard on a local GenLayer network (glsim, 5 validators): real leader/validator rounds, model mocked.

Every validator of the local network gets the same mocked model answers, so these tests show that the contract runs
through real consensus rounds (and that non-ASCII names survive the trip), not how a real model judges a name. glsim keeps
mocks for the whole run, so each test uses its own simulator.
"""
import json

import pytest

from rpc import RpcError, Sim

ALICE = "0x1111111111111111111111111111111111111111"
BOB = "0x2222222222222222222222222222222222222222"
CARL = "0x3333333333333333333333333333333333333333"


@pytest.fixture
def sim():
    simulator = Sim()
    try:
        yield simulator
    finally:
        simulator.close()


def mocks(sim, table):
    sim.rpc("sim_installMocks", web_mocks={}, llm_mocks={"BEGIN NEW NAME ---\\n" + k + "\\n": v for k, v in table.items()})


def say(sim, contract, method, who, *args):
    out = sim.call(contract, method, list(args), who)
    return json.loads(out) if isinstance(out, str) and out[:1] == "{" else out


def start(sim):
    return sim.deploy("contracts/lookalike_guard.py", [], ALICE)


def answer(confusing, target=0, shared=""):
    return json.dumps({"confusing": confusing, "target": target, "shared": shared})


def test_the_three_outcomes_through_five_validators(sim):
    c = start(sim)
    mocks(sim, {"paypall": answer(True, 1, "paypal"), "paypath": answer(False)})
    assert say(sim, c, "register", ALICE, "paypal") == {"status": "REGISTERED", "id": 0, "compared": 0}
    plain = say(sim, c, "register", BOB, "paypa1")                       # same skeleton: plain code, no model
    assert plain["status"] == "BLOCKED" and plain["kind"] == "CONFUSABLE" and plain["with"] == 0
    similar = say(sim, c, "register", BOB, "paypall")                    # near: the validators judge
    assert similar == {"status": "BLOCKED", "kind": "SIMILAR", "with": 0, "with_name": "paypal", "shared": "paypal"}
    assert say(sim, c, "register", BOB, "paypath") == {"status": "REGISTERED", "id": 1, "compared": 1}
    assert sim.read_json(c, "get_name_count") == 2
    log = sim.read_json(c, "get_refusals_page", [0, 10])
    assert [e["kind"] for e in log["items"]] == ["CONFUSABLE", "SIMILAR"]


def test_cyrillic_and_turkish_names_travel_through_the_network(sim):
    c = start(sim)
    assert say(sim, c, "register", ALICE, "хор")["status"] == "REGISTERED"          # Cyrillic
    blocked = say(sim, c, "register", BOB, "xop")                                    # Latin lookalike
    assert blocked["status"] == "BLOCKED" and blocked["with_name"] == "хор"
    assert say(sim, c, "register", ALICE, "Şırnak")["status"] == "REGISTERED"
    assert say(sim, c, "register", BOB, "sirnak")["kind"] == "CONFUSABLE"
    with pytest.raises(RpcError):
        say(sim, c, "register", CARL, "pаypal")                                      # Latin + Cyrillic in one name
    assert sim.read_json(c, "get_name_json", ["şırnak"])["name"] == "Şırnak"


def test_a_badly_formed_model_answer_changes_nothing(sim):
    c = start(sim)
    mocks(sim, {"paypall": "I think these are fine."})
    say(sim, c, "register", ALICE, "paypal")
    before = (sim.read(c, "get_name_count"), sim.read(c, "get_refusal_count"))
    with pytest.raises(RpcError):
        say(sim, c, "register", BOB, "paypall")
    assert (sim.read(c, "get_name_count"), sim.read(c, "get_refusal_count")) == before


def test_shared_characters_that_are_not_in_the_names_are_not_a_verdict(sim):
    c = start(sim)
    mocks(sim, {"paypall": answer(True, 1, "stripe")})
    say(sim, c, "register", ALICE, "paypal")
    with pytest.raises(RpcError):
        say(sim, c, "register", BOB, "paypall")
    assert sim.read(c, "get_name_count") == 1


def test_challenge_release_and_limits(sim):
    c = start(sim)
    tail = "--- END EXISTING NAMES ---\\n--- BEGIN NEW NAME ---\\n"
    sim.rpc("sim_installMocks", web_mocks={}, llm_mocks={
        "1\\. paypal\\n" + tail + "paypath\\n": answer(False),                         # registration of paypath
        "2\\. paypath\\n" + tail + "paypall\\n": answer(False),                        # registration of paypall (two candidates)
        "1\\. paypal\\n" + tail + "paypall\\n": answer(True, 1, "paypal"),             # the later challenge (one candidate)
    })
    say(sim, c, "register", ALICE, "paypal")
    say(sim, c, "register", CARL, "paypath")
    assert say(sim, c, "register", BOB, "paypall") == {"status": "REGISTERED", "id": 2, "compared": 2}   # the model let it through
    with pytest.raises(RpcError):
        say(sim, c, "challenge", CARL, "paypall", "paypal")                           # not the owner of paypal
    assert say(sim, c, "challenge", ALICE, "paypall", "paypal") == {"status": "UPHELD", "revoked": 2, "shared": "paypal"}
    assert sim.read_json(c, "get_name_by_id_json", [2])["status"] == "REVOKED"
    assert say(sim, c, "release", ALICE, "paypal") == {"status": "RELEASED", "id": 0}
    assert sim.read_json(c, "check_json", ["paypa1"])["confusable_with"] is None          # a released name blocks nothing
    with pytest.raises(RpcError):
        say(sim, c, "release", ALICE, "paypal")
