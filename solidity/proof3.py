#!/usr/bin/env python3
"""Continuacao da prova: vault 0xc937... ja inicializado com membros e deposito."""
import json, time
from pathlib import Path
from web3 import Web3
from eth_account import Account

RPC = "https://sepolia-rollup.arbitrum.io/rpc"
w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
assert w3.is_connected()
HERE = Path(__file__).parent
CA = "0xc937f1e44d037D5AcAC6e7f1016698650f900B19"
abi = json.loads((HERE / "out" / "AetherVault.sol" / "AetherVault.json").read_text())["abi"]
mock_art = json.loads((HERE / "out" / "AetherVault.sol" / "MockStrategy.json").read_text())
vault = w3.eth.contract(address=w3.to_checksum_address(CA), abi=abi)

DEPLOYER = Account.from_key("0xc5c66dff1c3cfae98bea54fc80598a69f680e2d83c22105ebff02c9ca87934bf")
ETH = 10**18
GAS = {"gas": 700000, "maxFeePerGas": w3.to_wei(0.05, "gwei"), "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei")}
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

print(f"vault: {CA} | balance: {vault.functions.ethBalance().call()} wei | deployer: {w3.eth.get_balance(DEPLOYER.address)}")
m2b, heirb, dest = Account.create(), Account.create(), Account.create()
p("4b. Novas contas (m2b, heirb, dest) + papeis")
for a in (m2b, heirb, dest):
    t = {"from": DEPLOYER.address, "to": a.address, "value": 150000000000000,
         "nonce": w3.eth.get_transaction_count(DEPLOYER.address, "pending"),
         "chainId": w3.eth.chain_id, "gas": 30000, **{k: GAS[k] for k in ("maxFeePerGas","maxPriorityFeePerGas")}}
    w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(DEPLOYER.sign_transaction(t).raw_transaction), timeout=60)
print(f"add m2b {txh(send(DEPLOYER, vault.functions.addMember(m2b.address, 100000000000000, 200000000000000)))}")
print(f"add heirb {txh(send(DEPLOYER, vault.functions.addMember(heirb.address, 50000000000000, 100000000000000)))}")
print(f"promote m2b->admin {txh(send(DEPLOYER, vault.functions.promoteMember(m2b.address)))}")
print(f"admins = {vault.functions.activeAdminCount().call()} | threshold = {vault.functions.threshold().call()}")

p("6. Multisig 2-de-3: proposta -> DUAS aprovacoes -> executa (0.00006 ETH)")
print(f"propose(m2b) {txh(send(m2b, vault.functions.proposeSpend(dest.address, 60000000000000, 60, False)))}")
must_revert("execute com 0/2 aprovacoes", m2b, vault.functions.executeProposal(1, b""))
print(f"approve(m2b) {txh(send(m2b, vault.functions.approveProposal(1)))}")
print(f"approve(deployer) {txh(send(DEPLOYER, vault.functions.approveProposal(1)))}")
print(f"execute {txh(send(m2b, vault.functions.executeProposal(1, b'')))}")
print(f"saldo dest = {w3.eth.get_balance(dest.address)} wei")

p("7. Gasto sob limite (heirb, 0.00002 ETH, sem multisig)")
print(f"withdraw {txh(send(heirb, vault.functions.withdrawUnderLimit(heirb.address, 20000000000000)))}")
must_revert("acima do limite diario (0.0002)", heirb, vault.functions.withdrawUnderLimit(heirb.address, 200000000000000))

p("8. Stream: 0.00005 ETH em 180s + claim parcial")
print(f"createStream {txh(send(DEPLOYER, vault.functions.createStream(heirb.address, 50000000000000, 180)))}")
time.sleep(8)
print(f"claim parcial {txh(send(heirb, vault.functions.withdrawStream(0)))}")

p("9. checkIn")
print(f"checkIn {txh(send(DEPLOYER, vault.functions.checkIn()))}")

p("10. Heranca: gracia 5s -> cedo bloqueia -> apos gracia herda")
print(f"setHeir {txh(send(DEPLOYER, vault.functions.setHeir(heirb.address, 5)))}")
must_revert("claim antes da gracia", heirb, vault.functions.claimAsHeir())
time.sleep(6)
print(f"claim {txh(send(heirb, vault.functions.claimAsHeir()))}")
print(f"novo owner = heirb? {vault.functions.owner().call() == heirb.address}")

p("11. Emergencia: freeze -> bloqueia -> timelock 60s -> unfreeze")
print(f"freeze {txh(send(heirb, vault.functions.emergencyFreeze(1)))}")
print(f"frozen={vault.functions.frozen().call()}")
must_revert("withdraw sob freeze", heirb, vault.functions.withdrawUnderLimit(heirb.address, 1000000000000))
must_revert("unfreeze antes do timelock", heirb, vault.functions.unfreeze())
time.sleep(62)
print(f"unfreeze {txh(send(heirb, vault.functions.unfreeze()))}")

p("12. Yield: MockStrategy 10%")
mock = w3.eth.contract(abi=mock_art["abi"], bytecode=mock_art["bytecode"]["object"])
rc = send(DEPLOYER, mock.constructor(w3.to_checksum_address(CA)), gas=2000000)
MOCK = w3.to_checksum_address(rc["contractAddress"])
print(f"mock deploy {txh(rc)}")
print(f"setStrategy {txh(send(heirb, vault.functions.setStrategy(MOCK)))}")
antes = vault.functions.ethBalance().call()
print(f"deployToStrategy {txh(send(heirb, vault.functions.deployToStrategy(20000000000000)))}")
print(f"harvest {txh(send(heirb, vault.functions.harvestFromStrategy(20000000000000)))}")
print(f"rendimento = +{vault.functions.ethBalance().call() - antes} wei")

p("13. Reciclagem")
for a in (m2b, heirb, dest):
    try:
        b = w3.eth.get_balance(a.address)
        t = {"from": a.address, "to": DEPLOYER.address, "value": b - 30000000000000,
             "nonce": w3.eth.get_transaction_count(a.address, "pending"),
             "chainId": w3.eth.chain_id, "gas": 30000, **{k: GAS[k] for k in ("maxFeePerGas","maxPriorityFeePerGas")}}
        w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(a.sign_transaction(t).raw_transaction), timeout=60)
    except Exception as e: print(f"  retorno parcial: {str(e)[:60]}")

p("RESUMO")
print(f"Contrato: {CA}")
print(f"{len(H)} txs desta rodada:")
for h in H: print("  https://sepolia.arbiscan.io/tx/" + h)
prev = json.loads((HERE / "PROOF_HASHES.json").read_text()) if (HERE / "PROOF_HASHES.json").exists() else {"contract": CA, "hashes": []}
(HERE / "PROOF_HASHES.json").write_text(json.dumps({"contract": CA, "hashes": prev["hashes"] + H}, indent=1))
print("PROOF_HASHES.json atualizado (rodadas somadas)")
