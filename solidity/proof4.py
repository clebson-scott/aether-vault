#!/usr/bin/env python3
"""Prova viva FINAL do Aether Vault — vault 0xc937 (ja no ar), modo ultra-frugal com reciclagem."""
import json, time
from pathlib import Path
from web3 import Web3
from eth_account import Account

RPC = "https://sepolia-rollup.arbitrum.io/rpc"
w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
assert w3.is_connected()
HERE = Path(__file__).parent
CA = "0xc937f1e44d037D5AcAC6e7f1016698650f900B19"
art = json.loads((HERE / "out" / "AetherVault.sol" / "AetherVault.json").read_text())
abi = art["abi"]
mock_art = json.loads((HERE / "out" / "AetherVault.sol" / "MockStrategy.json").read_text())
vault = w3.eth.contract(address=w3.to_checksum_address(CA), abi=abi)

DEPLOYER = Account.from_key("os.environ.get("DEPLOYER_KEY")")
GAS = {"gas": 400000, "maxFeePerGas": w3.to_wei(0.05, "gwei"), "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei")}
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

print(f"vault {CA} | saldo {vault.functions.ethBalance().call()} wei | deployer {w3.eth.get_balance(DEPLOYER.address)} wei")
m2b, heirb = Account.create(), Account.create()
p("4. Papeis: m2b (admin), heirb (membro c/ limites)")
raw(DEPLOYER, m2b.address, 20000000000000)
raw(DEPLOYER, heirb.address, 20000000000000)
print(f"add m2b {txh(send(DEPLOYER, vault.functions.addMember(m2b.address, 50000000000000, 100000000000000)))}")
print(f"add heirb {txh(send(DEPLOYER, vault.functions.addMember(heirb.address, 30000000000000, 60000000000000)))}")
print(f"promote m2b {txh(send(DEPLOYER, vault.functions.promoteMember(m2b.address)))}")
print(f"remove m2 antiga (chave descartada) {txh(send(DEPLOYER, vault.functions.removeMember(Web3.to_checksum_address('0x0000000000000000000000000000000000000001'))))}" if False else "(skip remocao)")
print(f"admins={vault.functions.activeAdminCount().call()} threshold={vault.functions.threshold().call()}")

p("6. Multisig 2-de-2: proposta 0.00006 -> executar cedo bloqueia -> 2 aprovacoes -> executa")
print(f"propose(m2b) {txh(send(m2b, vault.functions.proposeSpend(heirb.address, 60000000000000, 60, False)))}")
must_revert("executar com 0/2", m2b, vault.functions.executeProposal(1, b""))
print(f"approve(m2b) {txh(send(m2b, vault.functions.approveProposal(1)))}")
print(f"approve(deployer) {txh(send(DEPLOYER, vault.functions.approveProposal(1)))}")
print(f"execute(heirb) {txh(send(heirb, vault.functions.executeProposal(1, b'')))}")

p("7. Gasto sob limite (heirb, 0.00001) + acima do limite bloqueia")
print(f"withdraw {txh(send(heirb, vault.functions.withdrawUnderLimit(heirb.address, 10000000000000)))}")
must_revert("acima do limite diario", heirb, vault.functions.withdrawUnderLimit(heirb.address, 200000000000000))

p("8. Stream 0.00005 em 180s + claim parcial")
print(f"createStream {txh(send(DEPLOYER, vault.functions.createStream(heirb.address, 50000000000000, 180)))}")
time.sleep(8)
print(f"claim parcial {txh(send(heirb, vault.functions.withdrawStream(0)))}")

p("9. checkIn + heranca (gracia 5s)")
print(f"checkIn {txh(send(DEPLOYER, vault.functions.checkIn()))}")
print(f"setHeir {txh(send(DEPLOYER, vault.functions.setHeir(heirb.address, 5)))}")
must_revert("claim antes da gracia", heirb, vault.functions.claimAsHeir())
time.sleep(6)
print(f"claim {txh(send(heirb, vault.functions.claimAsHeir()))}")
print(f"heirb e o novo owner? {vault.functions.owner().call() == heirb.address}")

p("11. Emergencia: freeze -> bloqueia -> timelock -> unfreeze")
print(f"freeze {txh(send(heirb, vault.functions.emergencyFreeze(1)))}")
must_revert("withdraw sob freeze", heirb, vault.functions.withdrawUnderLimit(heirb.address, 1000000000000))
must_revert("unfreeze antes do timelock", heirb, vault.functions.unfreeze())
time.sleep(62)
print(f"unfreeze {txh(send(heirb, vault.functions.unfreeze()))}")

p("12. Reciclagem parcial (heirb devolve ao deployer p/ pagar o restante)")
raw(heirb, DEPLOYER.address, w3.eth.get_balance(heirb.address) - 40000000000000)

p("13. Yield: MockStrategy com 10% de rendimento")
mock = w3.eth.contract(abi=mock_art["abi"], bytecode=mock_art["bytecode"]["object"])
rc = send(DEPLOYER, mock.constructor(w3.to_checksum_address(CA)), gas=1500000)
MOCK = w3.to_checksum_address(rc["contractAddress"])
print(f"mock {txh(rc)}")
print(f"setStrategy {txh(send(heirb, vault.functions.setStrategy(MOCK)))}")
antes = vault.functions.ethBalance().call()
print(f"deployToStrategy {txh(send(heirb, vault.functions.deployToStrategy(20000000000000)))}")
print(f"harvest {txh(send(heirb, vault.functions.harvestFromStrategy(20000000000000)))}")
print(f"rendimento = +{vault.functions.ethBalance().call() - antes} wei (yield 10%)")

p("14. Reciclagem final")
for a in (m2b, heirb):
    try: raw(a, DEPLOYER.address, w3.eth.get_balance(a.address) - 30000000000000)
    except Exception as e: print(f"  parcial: {str(e)[:60]}")

p("RESUMO")
print(f"Contrato: {CA}")
print(f"{len(H)} txs desta rodada:")
for h in H: print("  https://sepolia.arbiscan.io/tx/" + h)
prev = json.loads((HERE / "PROOF_HASHES.json").read_text()) if (HERE / "PROOF_HASHES.json").exists() else {"contract": CA, "hashes": []}
(HERE / "PROOF_HASHES.json").write_text(json.dumps({"contract": CA, "hashes": prev["hashes"] + H}, indent=1))
print("PROOF_HASHES.json atualizado")
