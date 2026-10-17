#!/usr/bin/env python3
"""DEPLOY v2: Factory + ConditionOracle + YieldAdapter + SmartAccount + prova ao vivo."""
import json, time
from pathlib import Path
from web3 import Web3
from eth_account import Account
from eth_account.messages import encode_defunct

RPC = "https://sepolia-rollup.arbitrum.io/rpc"
w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
HERE = Path(__file__).parent
DEPLOYER = Account.from_key("0xc5c66dff1c3cfae98bea54fc80598a69f680e2d83c22105ebff02c9ca87934bf")
MFEE = w3.to_wei(0.021, "gwei"); PFEE = w3.to_wei(0.001, "gwei")
H = []
def txh(r):
    H.append(r["transactionHash"].hex()); return "https://sepolia.arbiscan.io/tx/" + r["transactionHash"].hex()
def art(name): return json.loads((HERE / "out" / "AetherStack.sol" / (name + ".json")).read_text())
def av_art(): return json.loads((HERE / "out" / "AetherVault.sol" / "AetherVault.json").read_text())
def send(acct, fn, value=0, gas=None):
    if gas is None:
        try: gas = min(int(w3.eth.estimate_gas(fn.build_transaction({"from": acct.address, "value": value})) * 1.6) + 60000, 8000000)
        except Exception as e:
            print("estimate falhou:", str(e)[:120]); raise
    t = fn.build_transaction({"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
                              "chainId": w3.eth.chain_id, "value": value,
                              "gas": gas, "maxFeePerGas": MFEE, "maxPriorityFeePerGas": PFEE})
    h = w3.eth.send_raw_transaction(acct.sign_transaction(t).raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
    assert r["status"] == 1, "REVERTIDA " + h.hex()
    return r
def find_event(rc, sig):
    sig_h = w3.keccak(text=sig).hex()
    for lg in rc["logs"]:
        if lg["topics"][0].hex() == sig_h: return lg
    return None

print("deployer:", w3.eth.get_balance(DEPLOYER.address), "wei")

# (passo 0 removido: saldo do deployer ja e suficiente)
def _art(n):
    return json.loads((HERE / "out" / "AetherStack.sol" / (n + ".json")).read_text())
def fa_art(): return _art("VaultFactory")
def or_art(): return _art("ConditionOracle")
def ya_art(): return _art("YieldAdapter")
def sa_art(): return _art("SmartAccount")

# (factory/oracle/condicao ja deployados na rodada anterior)
FAC = "0x8277EF094EdEef248CdA0Fd68bc5af953B01Ba45"
ORC = "0x81d09BB77e39899585d87E2960c429b430E275FD"
COND = bytes.fromhex("a981fe72b057853826e7e1b175d41e50cb1a98d2ca14ba69d54defd4126da5e0")
f = w3.eth.contract(address=w3.to_checksum_address(FAC), abi=fa_art()["abi"])
o = w3.eth.contract(address=w3.to_checksum_address(ORC), abi=or_art()["abi"])
ORAC = ORC
_oss = json.loads((HERE / "ORACLE_SIGNERS.json").read_text())
sg1 = Account.from_key(_oss["sg1"]["key"]); sg2 = Account.from_key(_oss["sg2"]["key"]); sg3 = Account.from_key(_oss["sg3"]["key"])

# (secao 3 concluida na rodada anterior: cofre criado, deposit, adapter, harvest)
NEWV = "0x47f22989D80ff1F02bb0a3F4103930264488B556"
YLD = "0x0C3eb6A9612A67aDF889EE4881cbbf4b42BFb581"
v_abi = av_art()["abi"]
nv = w3.eth.contract(address=w3.to_checksum_address(NEWV), abi=v_abi)
print("retomando no cofre existente:", NEWV, "| saldo:", nv.functions.ethBalance().call())

# --- 4. Porta condicional REAL: proposta com oraculo 2-de-3 ---
send(DEPLOYER, nv.functions.setOracleGate(ORAC), gas=300000)
pid = nv.functions.proposalCount().call()
send(DEPLOYER, nv.functions.proposeSpend(DEPLOYER.address, 5000000000000, 600, True), gas=300000)
send(DEPLOYER, nv.functions.approveProposal(pid), gas=300000)
print("proposta condicional criada:", pid)
# proof = condId(32) + sig(65) + sig(65) de 2 signatarios distintos
msg = w3.keccak(b"AETHER-GATE" + w3.eth.chain_id.to_bytes(32, "big") +
                bytes.fromhex(NEWV[2:].rjust(40, "0")) +
                pid.to_bytes(32, "big") + bytes(COND))
proof = bytes(COND)
from eth_account.messages import encode_defunct
for sg in (sg2, sg3):
    sig = sg.sign_message(encode_defunct(primitive=msg))
    proof += sig.r.to_bytes(32, "big") + sig.s.to_bytes(32, "big") + sig.v.to_bytes(1, "big")
rc = send(DEPLOYER, nv.functions.executeProposal(pid, proof), gas=600000)
print("EXECUTADA COM PORTA ORACULAR 2-de-3 |", txh(rc))

# --- 5. SmartAccount (AA minimal) + guardians + acao no cofre ---
sa = w3.eth.contract(abi=art("SmartAccount")["abi"], bytecode=art("SmartAccount")["bytecode"]["object"])
g1, g2, g3 = Account.create(), Account.create(), Account.create()
rc = send(DEPLOYER, sa.constructor(DEPLOYER.address, [g1.address, g2.address, g3.address]), gas=2000000)
ACC = w3.to_checksum_address(rc.contractAddress)
print("SMART ACCOUNT:", ACC, "|", txh(rc))
# a conta deposita no cofre pelo owner
sac = w3.eth.contract(address=ACC, abi=art("SmartAccount")["abi"])
data = nv.functions.deposit()._encoded_data if hasattr(nv.functions.deposit(), "_encoded_data") else nv.encode_abi("deposit", [])
rc = send(DEPLOYER, sac.functions.execute(w3.to_checksum_address(NEWV), 10000000000000, bytes.fromhex("d0e30db0")), gas=400000, value=10000000000000)
print("smart account depositou no cofre |", txh(rc))
# chave de sessao com teto de 0.00001 ETH
rc = send(DEPLOYER, sac.functions.setSessionKey(g1.address, int(time.time()) + 3600, 10000000000000), gas=300000)
print("session key criada (limite 0.00001 ETH) |", txh(rc))
# social recovery: 2 de 3 guardians trocam o owner
rc = send(g1, sac.functions.voteRecovery(g2.address), gas=300000)
send(DEPLOYER, w3.eth.account, value=0) if False else None
raw = {"from": DEPLOYER.address, "to": g2.address, "value": 10000000000000,
       "nonce": w3.eth.get_transaction_count(DEPLOYER.address, "pending"),
       "chainId": w3.eth.chain_id, "gas": 30000, "maxFeePerGas": MFEE, "maxPriorityFeePerGas": PFEE}
w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(DEPLOYER.sign_transaction(raw).raw_transaction), timeout=60)
rc = send(g2, sac.functions.voteRecovery(g2.address), gas=300000)
print("social recovery 2-de-3: novo owner = g2? ", sac.functions.owner().call() == g2.address, "|", txh(rc))

Path(HERE / "DEPLOY_V2.json").write_text(json.dumps({
  "factory": FACT, "oracle": ORAC, "condition_id": COND.hex(), "yield_adapter": YLD,
  "new_vault": NEWV, "old_vault": OLD, "smart_account": ACC,
  "oracle_signers": [sg1.address, sg2.address, sg3.address], "hashes": H}, indent=1))
print("\n===", len(H), "txs | salvo DEPLOY_V2.json ===")
for h in H: print("  https://sepolia.arbiscan.io/tx/" + h)
