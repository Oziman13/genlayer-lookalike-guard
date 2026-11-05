"""Mutation check: change the contract on a disposable copy, one small edit at a time, and see whether the tests notice.

Run from the repository root:  python3 scripts/mutation_check.py
It first proves that the unmodified contract passes, then runs the tests against every mutant (stopping at the first
failing test). A mutant that survives is either a missing test or an equivalent change; survivors are listed.
Each entry is (label, text to find, replacement, which occurrence of the text to change: 1 = first).
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CONTRACT = "contracts/lookalike_guard.py"

MUTANTS = [
    ("name min 4", "NAME_MIN, NAME_MAX = 3, 32", "NAME_MIN, NAME_MAX = 4, 32", 1),
    ("name max 33", "NAME_MIN, NAME_MAX = 3, 32", "NAME_MIN, NAME_MAX = 3, 33", 1),
    ("301 names", "MAX_NAMES = 300", "MAX_NAMES = 301", 1),
    ("six names per owner", "MAX_PER_OWNER = 5", "MAX_PER_OWNER = 6", 1),
    ("near is three", "NEAR = 2", "NEAR = 3", 1),
    ("near is one", "NEAR = 2", "NEAR = 1", 1),
    ("challenge near four", "CHALLENGE_NEAR = 3", "CHALLENGE_NEAR = 4", 1),
    ("challenge near two", "CHALLENGE_NEAR = 3", "CHALLENGE_NEAR = 2", 1),
    ("six candidates", "CANDIDATES = 5", "CANDIDATES = 6", 1),
    ("four candidates", "CANDIDATES = 5", "CANDIDATES = 4", 1),
    ("shared min 2", "SHARED_MIN = 3", "SHARED_MIN = 2", 1),
    ("shared min 4", "SHARED_MIN = 3", "SHARED_MIN = 4", 1),
    ("refusal log 101", "REFUSAL_LIMIT = 100", "REFUSAL_LIMIT = 101", 1),
    ("page limit 51", "PAGE_LIMIT = 50", "PAGE_LIMIT = 51", 1),
    ("model answer cap", "MAX_MODEL = 2000", "MAX_MODEL = 2001", 1),
    ("digraph rn dropped", '.replace("rn", "m")', "", 1),
    ("digraph vv dropped", '.replace("vv", "w")', "", 1),
    ("i and l kept apart", '.replace("i", "l")', "", 1),
    ("separators kept", 'out.append("".join(c for c in ch if c.isalnum()))', "out.append(ch)", 1),
    ("fold is case sensitive", "for ch in text.lower():", "for ch in text:", 1),
    ("zero is not o", "\"0o 1l", "\"0z 1l", 1),
    ("one is not l", " 1l 3e", " 1z 3e", 1),
    ("three is not e", " 3e 4a", " 3z 4a", 1),
    ("four is not a", " 4a 5s", " 4z 5s", 1),
    ("five is not s", " 5s 7t", " 5z 7t", 1),
    ("seven is not t", " 7t 8b", " 7z 8b", 1),
    ("eight is not b", " 8b\"", " 8z\"", 1),
    ("cyrillic a kept", "аa еe", "аz еe", 1),
    ("cyrillic e kept", " еe ", " еz ", 1),
    ("cyrillic o kept", " оo ", " оz ", 1),
    ("cyrillic p kept", " рp ", " рz ", 1),
    ("cyrillic c kept", " сc ", " сz ", 1),
    ("greek omicron kept", " οo ", " οz ", 1),
    ("turkish dotless i kept", "ıi çc", "ız çc", 1),
    ("turkish s cedilla kept", " şs ", " şz ", 1),
    ("turkish g breve kept", " ğg ", " ğz ", 1),
    ("o umlaut kept", " öo ", " öz ", 1),
    ("sharp s kept", " ßss ", " ßz ", 1),
    ("latin range starts late", "0xC0 <= o <= 0x24F", "0xC1 <= o <= 0x24F", 1),
    ("multiplication sign allowed", "o not in (0xD7, 0xF7)", "o not in (0xF7,)", 1),
    ("cyrillic supplement not cyrillic", "0x400 <= o <= 0x52F", "0x400 <= o <= 0x4FF", 1),
    ("cyrillic range starts late", "0x400 <= o <= 0x52F", "0x401 <= o <= 0x52F", 1),
    ("greek range starts late", "0x370 <= o <= 0x3FF", "0x371 <= o <= 0x3FF", 1),
    ("letters check skipped", "    if not ch.isalpha():\n        return \"\"", "    if False:\n        return \"\"", 1),
    ("type unchecked", "    if not isinstance(value, str):\n        return \"invalid name\"\n    value = value.strip()", "    value = value.strip()", 1),
    ("unsupported letters allowed", 'if kind == "other":\n            return "unsupported letters"', "if False:\n            return \"unsupported letters\"", 1),
    ("double separator allowed", "if previous_separator:\n                return \"invalid name\"", "if False:\n                return \"invalid name\"", 1),
    ("first character may be a digit", "if not value[0].isalpha() or value[-1] in SEPARATORS:", "if value[-1] in SEPARATORS:", 1),
    ("last character may be a separator", "if not value[0].isalpha() or value[-1] in SEPARATORS:", "if not value[0].isalpha():", 1),
    ("mixed scripts allowed", "if len(scripts) > 1:", "if False:", 1),
    ("mixed scripts need three", "if len(scripts) > 1:", "if len(scripts) > 2:", 1),
    ("name not stripped", "return value.strip()", "return value", 1),
    ("address case sensitive", "value = value.strip().lower()\n    if len(value) != 42", "value = value.strip()\n    if len(value) != 42", 1),
    ("taken check skipped", 'if self._active(self.by_key, key) is not None:\n            raise gl.vm.UserError("that name is taken")', "if False:\n            raise gl.vm.UserError(\"that name is taken\")", 1),
    ("taken check case sensitive", "key = name.lower()", "key = name", 1),
    ("registry full off by one", "if len(records) >= MAX_NAMES:", "if len(records) > MAX_NAMES:", 1),
    ("owner cap off by one", 'r["status"] == "ACTIVE") >= MAX_PER_OWNER', 'r["status"] == "ACTIVE") > MAX_PER_OWNER', 1),
    ("owner cap counts released names", 'if r["owner"] == who and r["status"] == "ACTIVE") >= MAX_PER_OWNER', 'if r["owner"] == who) >= MAX_PER_OWNER', 1),
    ("owner cap counts everyone", 'if r["owner"] == who and r["status"] == "ACTIVE") >= MAX_PER_OWNER', 'if r["status"] == "ACTIVE") >= MAX_PER_OWNER', 1),
    ("lookalike check skipped", "if twin is not None:\n            return", "if False:\n            return", 1),
    ("inactive names block", 'return record if record["status"] == "ACTIVE" else None', "return record", 1),
    ("model asked when nobody is near", "        if candidates:\n            existing", "        if True:\n            existing", 1),
    ("unreadable check passes", 'if reading["state"] != "OK":\n                raise gl.vm.UserError("the similarity check could not be read, try again")\n            if reading["confusing"]:\n                return', 'if False:\n                raise gl.vm.UserError("the similarity check could not be read, try again")\n            if reading["confusing"]:\n                return', 1),
    ("verdict ignored", 'if reading["confusing"]:\n                return', "if False:\n                return", 1),
    ("wrong name blamed", 'candidates[reading["target"]], reading["shared"])', 'candidates[0], reading["shared"])', 1),
    ("cleared note missing", 'check = "CLEARED_AGAINST_%d" % len(candidates)', 'check = "NO_NEIGHBOURS"', 1),
    ("refusal log uncapped", "if count < REFUSAL_LIMIT:", "if True:", 1),
    ("refusal count not kept", "self.refusal_count = u32(count + 1)", "pass", 1),
    ("released names are candidates", 'if record["status"] != "ACTIVE" or record["skeleton"] == skeleton:', 'if record["skeleton"] == skeleton:', 1),
    ("distance limit strict", "if distance <= limit:", "if distance < limit:", 1),
    ("candidates by age only", "found.sort(key=lambda item: (item[0], item[1]))", "found.sort(key=lambda item: item[1])", 1),
    ("candidates newest first", "found.sort(key=lambda item: (item[0], item[1]))", "found.sort(key=lambda item: (item[0], -item[1]))", 1),
    ("candidates farthest first", "found.sort(key=lambda item: (item[0], item[1]))", "found.sort(key=lambda item: (-item[0], item[1]))", 1),
    ("name index not kept", "self.by_key[key] = u32(name_id)", "pass", 1),
    ("skeleton index not kept", "self.by_skeleton[skeleton] = u32(name_id)", "pass", 1),
    ("name count not kept", "self.name_count = u32(name_id + 1)", "pass", 1),
    ("distance counts no substitutions", "previous[j - 1] + (0 if a[i - 1] == b[j - 1] else 1)", "previous[j - 1] + 0", 1),
    ("distance substitution is free", "previous[j - 1] + (0 if a[i - 1] == b[j - 1] else 1)", "previous[j - 1] + (0 if a[i - 1] == b[j - 1] else 2)", 1),
    ("release by anyone", 'if record["owner"] != _sender():\n            raise gl.vm.UserError("only the owner can release a name")', "if False:\n            raise gl.vm.UserError(\"only the owner can release a name\")", 1),
    ("release changes nothing", 'record["status"] = "RELEASED"', 'record["status"] = "ACTIVE"', 1),
    ("challenge by anyone", 'if older["owner"] != _sender():', "if False:", 1),
    ("challenge own name", 'if older["owner"] == newer["owner"]:', "if False:", 1),
    ("older must be older", 'if older["id"] >= newer["id"]:', "if False:", 1),
    ("older may equal newer", 'if older["id"] >= newer["id"]:', 'if older["id"] > newer["id"]:', 1),
    ("repeat challenge", 'if self.challenged.get(pair) is not None:', "if False:", 1),
    ("distance unchecked", 'if _distance(older["skeleton"], newer["skeleton"]) > CHALLENGE_NEAR:', "if False:", 1),
    ("challenge off by one", 'if _distance(older["skeleton"], newer["skeleton"]) > CHALLENGE_NEAR:', 'if _distance(older["skeleton"], newer["skeleton"]) >= CHALLENGE_NEAR:', 1),
    ("unreadable challenge passes", 'if reading["state"] != "OK":\n            raise gl.vm.UserError("the similarity check could not be read, try again")\n        if reading["confusing"]:\n            newer', 'if False:\n            raise gl.vm.UserError("the similarity check could not be read, try again")\n        if reading["confusing"]:\n            newer', 1),
    ("verdict ignored in challenge", 'if reading["confusing"]:\n            newer', "if True:\n            newer", 1),
    ("revocation not saved", 'newer["status"] = "REVOKED"', 'newer["status"] = "ACTIVE"', 1),
    ("revoker not noted", 'newer["revoked_by"] = older["id"]', 'newer["revoked_by"] = None', 1),
    ("upheld pair not recorded", 'self.challenged[pair] = "UPHELD"', "pass", 1),
    ("rejected pair not recorded", 'self.challenged[pair] = "REJECTED"', "pass", 1),
    ("unknown names tolerated", "if newer is None or older is None:", "if False:", 1),
    ("parser: wrong shape accepted", 'or set(raw) != {"confusing", "target", "shared"}', "", 1),
    ("parser: flag type unchecked", ' or type(raw["confusing"]) is not bool:', ":", 1),
    ("parser: clear answer may name a target", 'if raw["target"] != 0 or raw["shared"] != "":', "if False:", 1),
    ("parser: target type unchecked", "if type(number) is not int or not 1 <= number <= len(existing)", "if not 1 <= number <= len(existing)", 1),
    ("parser: target unbounded above", "not 1 <= number <= len(existing) or not isinstance(shared, str)", "not 1 <= number or not isinstance(shared, str)", 1),
    ("parser: shared type unchecked", " or not isinstance(shared, str):\n        raise ValueError(\"model answer names no existing name\")", ":\n        raise ValueError(\"model answer names no existing name\")", 1),
    ("parser: shared too short allowed", "if len(folded) < SHARED_MIN or folded not in new_skeleton or folded not in existing[number - 1][\"skeleton\"]:", "if folded not in new_skeleton or folded not in existing[number - 1][\"skeleton\"]:", 1),
    ("parser: shared not in the new name", "or folded not in new_skeleton or folded not in existing[number - 1]", "or folded not in existing[number - 1]", 1),
    ("parser: shared not in the old name", 'folded not in new_skeleton or folded not in existing[number - 1]["skeleton"]:', "folded not in new_skeleton:", 1),
    ("parser: shared taken as written", "folded = _fold(shared)", "folded = shared", 1),
    ("validator: wrong shape reading", 'if not isinstance(value, dict):\n        return False\n    if value == {"state": "ERROR"}:', 'if value == {"state": "ERROR"}:', 1),
    ("validator: state unchecked", 'if value.get("state") != "OK" or type(value.get("confusing")) is not bool:', 'if type(value.get("confusing")) is not bool:', 1),
    ("validator: clear reading with extras", 'return set(value) == {"state", "confusing"}', "return True", 1),
    ("validator: target unbounded", "and 0 <= target < len(existing)", "and 0 <= target", 1),
    ("validator: negative target", "and 0 <= target < len(existing)", "and target < len(existing)", 1),
    ("validator: shared not anchored", "and shared in new_skeleton and shared in existing[target][\"skeleton\"]", "", 1),
    ("validator: shared too short", "isinstance(shared, str) and len(shared) >= SHARED_MIN", "isinstance(shared, str)", 1),
    ("validator: non-canonical text", 'or proposed != _canonical(parsed):', ":", 1),
    ("validator: result type unchecked", "if not isinstance(result, gl.vm.Return):\n            return False\n        proposed", "proposed", 1),
    ("validator: size cap removed", "or len(proposed) > 2000:", ":", 1),
    ("validator: own state ignored", 'if parsed["state"] != mine["state"]:', "if False:", 1),
    ("validator: errors disagree", 'if parsed["state"] == "ERROR":\n            return True', 'if parsed["state"] == "ERROR":\n            return False', 1),
    ("validator: verdict ignored", 'if parsed["confusing"] != mine["confusing"]:', "if False:", 1),
    ("validator: target ignored", 'return not parsed["confusing"] or parsed["target"] == mine["target"]', "return True", 1),
    ("check_json: invalid names raise", 'if error:\n            return json.dumps({"valid": False', "if False:\n            return json.dumps({\"valid\": False", 1),
    ("check_json: taken always false", 'taken = self._active(self.by_key, clean.lower()) is not None', "taken = False", 1),
    ("lookup is case sensitive", "record = self._active(self.by_key, name.strip().lower())", "record = self._active(self.by_key, name.strip())", 1),
    ("lookup accepts bad names", "if _name_error(name):\n            return \"NONE\"", "if False:\n            return \"NONE\"", 1),
    ("by-id view type unchecked", "if type(name_id) is not int or name_id < 0 or name_id >= int(self.name_count):", "if name_id >= int(self.name_count):", 1),
    ("owner view shows everyone", 'for r in self._all() if r["owner"] == who]', "for r in self._all()]", 1),
    ("page type unchecked", "if type(offset) is not int or type(limit) is not int or offset < 0 or not 1 <= limit <= PAGE_LIMIT:\n            raise gl.vm.UserError(\"bad page\")\n        total = int(self.name_count)", "if offset < 0 or not 1 <= limit <= PAGE_LIMIT:\n            raise gl.vm.UserError(\"bad page\")\n        total = int(self.name_count)", 1),
    ("page limit unchecked", "or not 1 <= limit <= PAGE_LIMIT:\n            raise gl.vm.UserError(\"bad page\")\n        total = int(self.refusal_count)", "or False:\n            raise gl.vm.UserError(\"bad page\")\n        total = int(self.refusal_count)", 1),
]


def run_tests(directory: Path) -> bool:
    result = subprocess.run([sys.executable, "-m", "pytest", "tests/direct", "-q", "-x", "-p", "no:cacheprovider"],
                            cwd=directory, capture_output=True, text=True)
    return result.returncode == 0


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="mutation-") as tmp:
        work = Path(tmp)
        shutil.copytree(ROOT / "contracts", work / "contracts")
        shutil.copytree(ROOT / "tests", work / "tests")
        source = (ROOT / CONTRACT).read_text()
        if not run_tests(work):
            print("The unmodified contract does not pass its tests; stopping.")
            return 2
        print("base: tests pass on the unmodified contract")
        killed, survived = 0, []
        for label, old, new, nth in MUTANTS:
            if source.count(old) < nth:
                print("ANCHOR MISSING:", label)
                return 3
            parts = source.split(old)
            mutated = old.join(parts[:nth]) + new + old.join(parts[nth:])
            (work / CONTRACT).write_text(mutated)
            if run_tests(work):
                survived.append(label)
                print("SURVIVED:", label)
            else:
                killed += 1
        print("mutants: %d, killed: %d, survived: %d" % (len(MUTANTS), killed, len(survived)))
        for label in survived:
            print(" -", label)
        return 0


if __name__ == "__main__":
    sys.exit(main())
