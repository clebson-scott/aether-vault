#!/usr/bin/env python3
"""v2c: oraculo fixado + porta condicional + SmartAccount + DEPLOY_V2.json final."""
import json, time, re
from pathlib import Path
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct

RPC = "https://sepolia-rollup.arbitrum.io/rpc"
w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
HERE = Path(__file__).parent
DEPLOYER = Account.from_key("os.environ.get("DEPLOYER_KEY")")
MFEE = w3.to_wei(0.025, "gwei"); PFEE = w3.to_wei(0.001, "gwei")
H = []
def txh(r):
    H.append(r["transactionHash"].hex()); return "https://sepolia.arbiscan.io/tx/" + r["transactionHash"].hex()
def art(n): return json.loads((HERE / "out" / "AetherStack.sol" / (n + ".json")).read_text())
def av_art(): return json.loads((HERE / "out" / "AetherVault.sol" / "AetherVault.json").read_text())
def send(acct, fn, value=0, gas=1200000):
    t = fn.build_transaction({"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
                              "chainId": w3.eth.chain_id, "value": value,
                              "gas": gas, "maxFeePerGas": MFEE, "maxPriorityFeePerGas": PFEE})
    h = w3.eth.send_raw_transaction(acct.sign_transaction(t).raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
    assert r["status"] == 1, "REVERTIDA " + h.hex()
    return r
def find_event(rc, sig):
    sh = w3.keccak(text=sig).hex()
    for lg in rc["logs"]:
        if lg["topics"][0].hex() == sh: return lg

NEWV = "0x47f22989D80ff1F02bb0a3F4103930264488B556"
YLD = "0x0C3eb6A9612A67aDF889EE4881cbbf4b42BFb581"
nv = w3.eth.contract(address=w3.to_checksum_address(NEWV), abi=av_art()["abi"])
oss = json.loads((HERE / "ORACLE_SIGNERS.json").read_text())
sg1 = Account.from_key(oss["sg1"]["key"]); sg2 = Account.from_key(oss["sg2"]["key"]); sg3 = Account.from_key(oss["sg3"]["key"])
print("cofre:", NEWV, "| saldo:", nv.functions.ethBalance().call())

# 1. redeploy do oracolo (staticcall-safe) com os mesmos signatarios 2-de-3
o = w3.eth.contract(abi=art("ConditionOracle")["abi"], bytecode=art("ConditionOracle")["bytecode"]["object"])
rc = send(DEPLOYER, o.constructor([sg1.address, sg2.address, sg3.address], 2))
ORAC = w3.to_checksum_address(rc.contractAddress)
o = w3.eth.contract(address=ORAC, abi=art("ConditionOracle")["abi"])
print("ORACLE v2:", ORAC, "|", txh(rc))
# sg1 registra condicao (ja tem gas da rodada 1)
rc = send(sg1, o.functions.registerCondition("BTC acima de 100k USD"), gas=300000)
COND = find_event(rc, "ConditionRegistered(bytes32,string,uint256)")["topics"][1]
print("CONDICAO:", COND.hex(), "|", txh(rc))

# 2. porta condicional no cofre: proposta exige oraculo
send(DEPLOYER, nv.functions.setOracleGate(ORAC), gas=300000)
pid = nv.functions.proposalCount().call()
send(DEPLOYER, nv.functions.proposeSpend(DEPLOYER.address, 5000000000000, 600, True), gas=300000)
send(DEPLOYER, nv.functions.approveProposal(pid), gas=300000)
print("proposta condicional", pid, "criada e aprovada")
msg = w3.keccak(b"AETHER-GATE" + w3.eth.chain_id.to_bytes(32, "big") +
                bytes.fromhex(NEWV[2:].rjust(40, "0")) + pid.to_bytes(32, "big") + bytes(COND))
proof = bytes(COND)
for sg in (sg2, sg3):
    sig = sg.sign_message(encode_defunct(primitive=msg))
    proof += sig.r.to_bytes(32, "big") + sig.s.to_bytes(32, "big") + sig.v.to_bytes(1, "big")
rc = send(DEPLOYER, nv.functions.executeProposal(pid, proof), gas=600000)
print("PROPOSTA EXECUTADA COM PORTA ORACULAR 2-de-3 |", txh(rc))

# 3. SmartAccount + interacao com o cofre + session key + social recovery
sa = w3.eth.contract(abi=art("SmartAccount")["abi"], bytecode=art("SmartAccount")["bytecode"]["object"])
g1, g2, g3 = Account.create(), Account.create(), Account.create()
rc = send(DEPLOYER, sa.constructor(DEPLOYER.address, [g1.address, g2.address, g3.address]), gas=2500000)
ACC = w3.to_checksum_address(rc.contractAddress)
print("SMART ACCOUNT:", ACC, "|", txh(rc))
sac = w3.eth.contract(address=ACC, abi=art("SmartAccount")["abi"])
# deposit via smart account (calldata de deposit() = seletor)
sel = nv.encode_abi("deposit", []) if hasattr(nv, "encode_abi") else bytes.fromhex("d0e30db0")
rc = send(DEPLOYER, sac.functions.execute(w3.to_checksum_address(NEWV), 10000000000000, bytes.fromhex("d0e30db0")), gas=400000, value=10000000000000)
print("smart account depositou no cofre |", txh(rc))
rc = send(DEPLOYER, sac.functions.setSessionKey(g1.address, int(time.time()) + 3600, 10000000000000), gas=300000)
print("session key criada (teto 0.00001 ETH/h) |", txh(rc))
# gas p/ guardians votarem
for gg in (g1, g2):
    t = {"from": DEPLOYER.address, "to": gg.address, "value": 8000000000000,
         "nonce": w3.eth.get_transaction_count(DEPLOYER.address, "pending"),
         "chainId": w3.eth.chain_id, "gas": 30000, "maxFeePerGas": MFEE, "maxPriorityFeePerGas": PFEE}
    w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(DEPLOYER.sign_transaction(t).raw_transaction), timeout=60)
rc = send(g1, sac.functions.voteRecovery(g2.address), gas=300000)
rc = send(g2, sac.functions.voteRecovery(g2.address), gas=300000)
print("social recovery 2-de-3: novo owner e g2?", sac.functions.owner().call() == g2.address, "|", txh(rc))

# 4. DEPLOY_V2.json final com TODOS os enderecos e hashes de todas as rodadas
allh = []
for f in sorted(HERE.glob('v2run*.log')) + [HERE/'final2.log']:
    allh += re.findall(r'arbiscan\.io/tx/([0-9a-fA-F]{64})', f.read_text())
allh += H
seen, out = set(), []
for h in allh:
    h = h.lower()
    if h not in seen: seen.add(h); out.append("0x"+h)
(HERE / "DEPLOY_V2.json").write_text(json.dumps({
  "contracts": {
    "VaultFactory": {"address": "0x8277EF094EdEef248CdA0Fd68bc5af953B01Ba45", "deploy_tx": "0x222677b1f021fc0f54ae894f70d53bee799406080140c03d09b7fc5b8181efa6"},
    "ConditionOracle": {"address": ORAC, "condition_id": "0x"+COND.hex(), "signers": [sg1.address, sg2.address, sg3.address], "threshold": 2},
    "YieldAdapter": {"address": YLD, "deploy_tx": "0x0722265938e992921900c27849109641c3b39d58bd56b6c7d877042b43e7d670"},
    "VaultViaFactory": {"address": NEWV, "create_tx": "0x19b4f1094aef5bff4cd0bfbbbecc6094f844a50c3cc97cbc2287db132ee027d7"},
    "SmartAccount": {"address": ACC}
  },
  "proof_hashes": out}, indent=1))
print("\n===", len(out), "hashes on-chain | DEPLOY_V2.json salvo ===")
for h in out: print("  0x"+h.lower().replace("0x",""))
