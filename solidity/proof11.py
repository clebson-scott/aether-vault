#!/usr/bin/env python3
"""PROOF11 — FINAL: heranca com herdeiro novo + emergencia + yield. Orçamento milimetrico."""
import json, time
from pathlib import Path
from web3 import Web3
from eth_account import Account

RPC = "https://sepolia-rollup.arbitrum.io/rpc"
w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
HERE = Path(__file__).parent
CA = "0xc937f1e44d037D5AcAC6e7f1016698650f900B19"
abi = json.loads((HERE / "out" / "AetherVault.sol" / "AetherVault.json").read_text())["abi"]
mock_art = json.loads((HERE / "out" / "AetherVault.sol" / "MockStrategy.json").read_text())
vault = w3.eth.contract(address=w3.to_checksum_address(CA), abi=abi)
DEPLOYER = Account.from_key("0xc5c66dff1c3cfae98bea54fc80598a69f680e2d83c22105ebff02c9ca87934bf")
K = json.loads((HERE / "KEYS.json").read_text())
heirb2 = Account.from_key(K["heirb2"])

GAS = {"gas": 350000, "maxFeePerGas": w3.to_wei(0.05, "gwei"), "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei")}
H = []
def txh(r):
    H.append(r["transactionHash"].hex()); return f"tx https://sepolia.arbiscan.io/tx/{r['transactionHash'].hex()}"
def send(acct, fn, value=0, gas=None):
    g = dict(GAS); g["gas"] = gas or GAS["gas"]
    t = fn.build_transaction({"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
                              "chainId": w3.eth.chain_id, "value": value, **g})
    h = w3.eth.send_raw_transaction(acct.sign_transaction(t).raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=90)
    assert r["status"] == 1, f"REVERTIDA: {h.hex()}"
    return r
def must_revert(label, acct, fn, value=0):
    try:
        send(acct, fn, value); print(f"  ✗ {label}: NAO reverteu (PROBLEMA)")
    except Exception:
        print(f"  ✓ {label}: revertida como esperado")
def p(t): print(f"\n=== {t} ===")
def raw(acct, to, value):
    t = {"from": acct.address, "to": to, "value": value, "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
         "chainId": w3.eth.chain_id, "gas": 30000, "maxFeePerGas": w3.to_wei(0.05, "gwei"), "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei")}
    w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(acct.sign_transaction(t).raw_transaction), timeout=60)

print(f"deployer: {w3.eth.get_balance(DEPLOYER.address)} | heirb2: {w3.eth.get_balance(heirb2.address)}")
p("0. Reciclar heirb2 p/ destravar o orcamento")
raw(heirb2, DEPLOYER.address, w3.eth.get_balance(heirb2.address) - 25000000000000)
print(f"deployer agora: {w3.eth.get_balance(DEPLOYER.address)}")

heir3 = Account.create()
p("F2. Heranca: setHeir(heir3) -> nao-herdeiro bloqueia -> claim -> herda")
print(f"setHeir {txh(send(DEPLOYER, vault.functions.setHeir(heir3.address, 5)))}")
raw(DEPLOYER, heir3.address, 25000000000000)
must_revert("claim por nao-herdeiro (heirb2)", heirb2, vault.functions.claimAsHeir())
print(f"claim(heir3) {txh(send(heir3, vault.functions.claimAsHeir(), gas=450000))}")
print(f"heir3 e o novo owner? {vault.functions.owner().call() == heir3.address}")

p("G. Emergencia: freeze -> bloqueia -> timelock 60s -> unfreeze")
print(f"freeze {txh(send(heir3, vault.functions.emergencyFreeze(1)))}")
print(f"frozen={vault.functions.frozen().call()}")
must_revert("withdraw sob freeze", heirb2, vault.functions.withdrawUnderLimit(heirb2.address, 1000000000000))
must_revert("unfreeze antes do timelock", heir3, vault.functions.unfreeze())
time.sleep(62)
print(f"unfreeze {txh(send(heir3, vault.functions.unfreeze()))}")

p("H. Reciclagem p/ o yield")
raw(heir3, DEPLOYER.address, w3.eth.get_balance(heir3.address) - 20000000000000)
raw(DEPLOYER, heir3.address, 20000000000000)

p("I. Yield: MockStrategy 10%")
mock = w3.eth.contract(abi=mock_art["abi"], bytecode=mock_art["bytecode"]["object"])
rc = send(DEPLOYER, mock.constructor(w3.to_checksum_address(CA)), gas=500000)
MOCK = w3.to_checksum_address(rc["contractAddress"])
print(f"mock {txh(rc)}")
print(f"setStrategy {txh(send(heir3, vault.functions.setStrategy(MOCK)))}")
antes = vault.functions.ethBalance().call()
print(f"deployToStrategy {txh(send(heir3, vault.functions.deployToStrategy(15000000000000)))}")
print(f"harvest {txh(send(heir3, vault.functions.harvestFromStrategy(15000000000000)))}")
print(f"rendimento = +{vault.functions.ethBalance().call() - antes} wei (yield 10%)")

p("J. Reciclagem final")
for a in (heir3, heirb2):
    try: raw(a, DEPLOYER.address, w3.eth.get_balance(a.address) - 25000000000000)
    except Exception as e: print(f"  parcial: {str(e)[:60]}")

p("RESUMO")
print(f"Contrato: {CA}")
print(f"{len(H)} txs desta rodada:")
for h in H: print("  https://sepolia.arbiscan.io/tx/" + h)
prev = json.loads((HERE / "PROOF_HASHES.json").read_text()) if (HERE / "PROOF_HASHES.json").exists() else {"contract": CA, "hashes": []}
(HERE / "PROOF_HASHES.json").write_text(json.dumps({"contract": CA, "hashes": prev["hashes"] + H}, indent=1))
print("PROOF_HASHES.json atualizado")
