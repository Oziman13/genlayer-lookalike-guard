# Lookalike Guard

**A name registry that refuses a name built to be mistaken for one that is already taken.** Plain code catches the look-alike
tricks (`paypa1`, `pay-pal`, a Cyrillic `а`, a Turkish `ı`); validators judge only the cases that need judgement (`paypall` next to
`paypal`).

Anyone can register a name. Before it is accepted the contract folds it to a **skeleton** (what it looks like once the tricks are
removed) and compares it with every active name. A twin is refused by code alone. A near neighbour is put to the validators, who must
agree, exactly, on whether the new name imitates it and on which name it imitates. The owner of an older name can also challenge a newer
one afterwards.

* `contracts/lookalike_guard.py` : the Intelligent Contract (one Python file, no funds, no web access).
* `tests/direct` : 269 direct-mode tests with the model mocked. `tests/glsim` : 5 tests on a local 5-validator network.
* `scripts/mutation_check.py` : breaks the contract on purpose in 126 ways (116 caught; the rest cannot change a result, see `evidence/mutation-checks.txt`).
* `evidence/` : the outputs of those runs.

Status: **v0.1.0, deployed on Studionet and tried with the real validators**. See [Live run](#live-run) and [What it does not show](#what-it-does-not-show).

## Why a contract for this

A registry of names (handles, project names, token tickers) is only worth something if one name cannot pass for another. Two different
failures sit under that. One is mechanical: `paypa1`, `PayPaI` (capital i), `pay_pal`, `раураl` with Cyrillic letters. That needs a
fixed rule, the same on every validator, and no model. The other is a matter of reading: `paypall`, `paypal-official`: is this a copy-cat
or a different name that happens to be close? That is the only place a model is used, and only for names that are already close in
plain code. Everything else (limits, ownership, release, the lists) is plain code.

## How it works

| Step | What happens |
|---|---|
| `register(name)` | 3 to 32 characters: letters, digits and `_ - .`; it must start with a letter and not end with a separator. Latin, Cyrillic and Greek letters are accepted, and **mixing scripts in one name is refused**. |
| 1. Exact | The same name in any letter case is "taken". |
| 2. Skeleton (code) | If an active name has the same skeleton, the new name is **BLOCKED as CONFUSABLE**. No model. |
| 3. Neighbours (code) | The active names within edit distance 2 (on skeletons), at most five, closest first then oldest, become the candidates. None: the name is registered with no model call. |
| 4. Model (validators) | The model must say whether the new name imitates one candidate, name that candidate, and give at least three characters shared by both names. The contract checks that those characters are really in both skeletons. Validators must agree exactly on the verdict and the candidate. A confusing verdict is **BLOCKED as SIMILAR**. |
| Refusal | Written to a public log (first 100 entries) with the name, the address, the kind, the name it clashed with and the shared characters. The call returns normally. |
| `challenge(name, against)` | The owner of the older name `against` asks for the newer `name` (within edit distance 3) to be revoked. The same validator question is asked about that one pair. Upheld: the newer name is `REVOKED`. Each pair can be challenged once. |
| `release(name)` | The owner gives a name back; it can be registered again, with the same checks. |

### The skeleton

Lower case; accents and Turkish letters folded (`ş` to `s`, `ı` to `i`, `ö` to `o`, `ç` to `c`, `ğ` to `g`, `ü` to `u`); Cyrillic
and Greek look-alikes folded to Latin (`а е о р с у х і ј ѕ һ ԁ ԛ ԝ к м н т в ѵ`, `α ο ν ρ ι κ τ υ χ ε β η ω`); digits that pass for letters folded
(`0 o`, `1 l`, `3 e`, `4 a`, `5 s`, `7 t`, `8 b`); `i` and `l` treated as the same letter; `rn` read as `m` and `vv` as `w`; separators
removed. `check_json(name)` shows the skeleton and what a name would meet, without storing anything.

## Contract

| Call | Kind | What it does |
|---|---|---|
| `register(name)` | write | `{"status": "REGISTERED", "id", "compared"}` or `{"status": "BLOCKED", "kind": "CONFUSABLE" \| "SIMILAR", "with", "with_name", "shared"}`. |
| `release(name)` | write | Give a name back (owner only). |
| `challenge(name, against)` | write | `{"status": "UPHELD", ...}` or `{"status": "REJECTED"}`. |
| `check_json(name)` | view | Dry run of the plain-code step: validity, skeleton, whether it is taken, the active name with the same skeleton, the neighbours the model would be asked about. |
| `get_name_json(name)`, `get_name_by_id_json(id)`, `get_owner_json(address)` | view | A record (`id`, `name`, `skeleton`, `owner`, `status`, `check`, `revoked_by`); every record of an address. |
| `get_name_count()`, `get_names_page(offset, limit)`, `get_refusal_count()`, `get_refusals_page(offset, limit)` | view | List names and the refusal log. |

Limits: 300 records, 5 active names per address, 100 refusal-log entries.

## What it does not show

These are limits of the idea, not bugs.

* **The fold table is finite.** It covers the Latin, Cyrillic and Greek look-alikes written out above, not every Unicode confusable.
  Other scripts are refused (`unsupported letters`) instead of guessed at. A look-alike not in the table is treated as a different letter.
* **A skeleton collision can block an honest name.** `lamp` and `iamp` have one skeleton; so do `mia` and `rnia`. The refusal is logged with the
  name it clashed with, so the owner can pick another name.
* **You cannot register a look-alike of your own name.** The rule does not look at who is asking.
* **The model's part is a judgement.** "Imitates" is not a fact. The prompt says to answer "not confusing" when in doubt; that lowers false
  blocks and raises missed copy-cats, which is what `challenge` is for. The model sees the names only, not what they are used for.
* **Exact agreement is demanded.** Validators must agree exactly on the verdict and the candidate. If they cannot, the transaction
  does not settle and can be sent again; nothing is stored in between.
* **A challenge can be used against an honest owner**, which is why validators decide it and why a pair can be challenged only once.
* **Addresses are not identities.** Anyone can use many addresses. The caps (5 names per address, 300 records) limit how fast the
  registry fills, they do not stop it.
* **A name here protects nothing outside this contract.**
* No funds are held.

## Tests

Run from the repository root (Python 3.12+, `pip install genlayer-test`).

```
python3 -m pytest tests/direct     # 269 tests, in memory, the model is mocked
python3 -m pytest tests/glsim      # 5 tests on a local 5-validator network (pip install glsim fastapi uvicorn)
python3 scripts/mutation_check.py  # 126 deliberate breakages
```

The skeleton is checked against a written-out table for every folded letter, and against random disguises (digits, accents, capital I,
separators, all-Cyrillic spellings) generated independently of the contract. Random registries are checked against a plain reference
implementation of edit distance. The tests mock the model, so they show that the contract handles each kind of answer correctly
(confusing, not confusing, badly formed, shared characters not in the names, forged validator readings), **not** how well a real model
spots a copy-cat. The mock answers on the local network are identical for every validator.

## Live run

Studionet, contract `0xB381c857377154B24B9BFD3FdB43Df42E897bDFB`
([Explorer](https://explorer-studio.genlayer.com/address/0xB381c857377154B24B9BFD3FdB43Df42E897bDFB)), one Studio account.

Three registrations were sent with the real validators and the real model:

| Name | Result | Decided by |
|---|---|---|
| `paypal` | `REGISTERED` | code (no neighbours) |
| `paypa1` | refused, `CONFUSABLE` | code only (same skeleton as `paypal`, no model) |
| `paypall` | refused, `SIMILAR` | the validators (one edit away from `paypal`) |

Afterwards the name count was 1 and the refusal log held 2 entries. `release` and `challenge` were not run on Studionet, and only these
three names were tried, so how the model judges less obvious pairs was not tested live.

## Where each claim is in the code

| Claim | Where |
|---|---|
| The skeleton | `FOLD`, `_fold` |
| One script per name, accepted letters | `_script`, `_name_error` |
| A twin skeleton is refused with no model | `LookalikeGuard.register` |
| Candidates: distance, order, cap | `LookalikeGuard._near`, `_distance` |
| The reading must name a candidate and shared characters that are in both names | `_parse` |
| Validators agree exactly on verdict and candidate and re-check the anchor | `_consensus` (`validator`), `_valid_reading` |
| An unreadable answer is never a verdict | `_read`, `register`, `challenge` |
| Challenges: older name, owner, distance, once per pair | `LookalikeGuard.challenge` |

## Licence

MIT, see `LICENSE`.
