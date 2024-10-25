
import json
from nftables import Nftables

nft = Nftables()
nft.set_json_output(True)

class NftError(Exception):
    pass

def nfc(cmd, *, throw=True):
    if isinstance(cmd, list):
        cmd = { "nftables": cmd }

    if isinstance(cmd, dict):
        if "nftables" not in cmd:
            cmd = { "nftables": [cmd] }
        rc, output, error = nft.json_cmd(cmd)
    else:
        rc, output, error = nft.cmd(cmd)

    if rc != 0 and throw:
        raise NftError(error)

    if nft.get_json_output() and isinstance(output, str) and output != "":
        output = json.loads(output)

    if isinstance(output, dict):
        output = output["nftables"]

    return output

def _extract_fq_table(*args):
    if len(args) == 1:
        table = args[0]
        return (table["family"], table["name"])
    elif len(args) == 2:
        return args
    else:
        raise ValueError("Invalid number of arguments")

def _extract_fq_chain(*args):
    if len(args) == 1:
        chain = args[0]
        return (chain["family"], chain["table"], chain["name"])
    elif len(args) == 3:
        return args
    else:
        raise ValueError("Invalid number of arguments")


def list_table_chains(*args):
    extracted = _extract_fq_table(*args)
    family, table = extracted
    ruleset = nfc(f"list table {' '.join(extracted)}")
    chains = [chain["chain"] for chain in ruleset if "chain" in chain and chain["chain"]["table"] == table]
    return chains

def list_chain_rules(*args):
    extracted = _extract_fq_chain(*args)
    family, table, chain = extracted
    ruleset = nfc(f"list chain {' '.join(extracted)}")
    rules = [rule["rule"] for rule in ruleset if "rule" in rule and rule["rule"]["table"] == table and rule["rule"]["chain"] == chain]
    return rules

def get_map_elements(*args):
    extracted = _extract_fq_chain(*args)
    data = nfc(f"list map {' '.join(extracted)}")
    themap = {}
    mapobj = data[1]["map"]
    if "elem" in mapobj:
        for elem in mapobj["elem"]:
            themap[elem[0]] = elem[1]
    return themap

def sync_chain_rules(chain, rules, *, tag=None):
    """ 
    Synchronize the rules of a chain with the given rules.
    If a tag is given, only rules with that tag will be deleted.
    """
    current_rules = list_chain_rules(chain["family"], chain["table"], chain["name"])

    if tag:
        tag = normalize_tag(tag)
        current_rules = [rule for rule in current_rules if "comment" in rule and rule["comment"].startswith(tag)]

    unmatched_existing = { r["handle"]: r for r in current_rules }

    commands = []

    for rule in rules:
        rule = { **rule }
        if tag and "comment" in rule and rule["comment"]:
            if not rule["comment"].startswith(tag):
                rule["comment"] = f"{tag} {rule['comment']}"

            matching_rule = findMatchingRule(current_rules, rule, by_comment=True)
            if matching_rule:
                unmatched_existing.pop(matching_rule["handle"], None)
                if not rulesEqual(matching_rule, rule, by_comment=False):
                    commands.append({ "replace": { "rule": { "handle": matching_rule["handle"], **rule } }})
            else:
                commands.append({ "insert": { "rule": rule }})
        else:
            if tag: rule["comment"] = tag
            matching_rule = findMatchingRule(current_rules, rule, by_comment=False)
            if matching_rule:
                unmatched_existing.pop(matching_rule["handle"], None)
            else:
                commands.append({ "insert": { "rule": rule }})

    for old_rule in unmatched_existing.values():
        commands.append({ "delete": { "rule": old_rule } })

    if commands:
        nfc(commands)

def removeRuleFromChain(chain, rule):
    rules = list_chain_rules(chain)
    if "handle" not in rule:
        rule = findMatchingRule(rules, rule)
        if not rule: return
    nfc({ "delete": { "rule": rule } })

def removeTaggedRulesFromChain(chain, tag):
    tag = normalize_tag(tag)
    rules = list_chain_rules(chain)
    matching_rules = [r for r in rules if "comment" in r and r["comment"].startswith(tag)]
    for rule in matching_rules:
        nfc({ "delete": { "rule": rule } })

def findMatchingRule(rules, rule, *, by_comment=False):
    for r in rules:
        if rulesEqual(r, rule, by_comment=by_comment):
            return r
    return None

def rulesEqual(rule1, rule2, *, by_comment=False):
    if rule1["table"] != rule2["table"]:
        return False
    if rule1["chain"] != rule2["chain"]:
        return False
    if by_comment and rule1["comment"] and rule1["comment"] == rule2["comment"]:
        return True
    if rule1["comment"] != rule2["comment"]:
        return False
    if rule1["expr"] != rule2["expr"]:
        return False
    return True

def rule_for_chain(chain, rule):
    return { "family": chain["family"], "table": chain["table"], "chain": chain["name"], **rule }

def normalize_tag(tag):
    if not tag.startswith("["): tag = f"[{tag}"
    if not tag.endswith("]"): tag = f"{tag}]"
    return tag
