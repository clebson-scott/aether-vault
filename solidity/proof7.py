#!/usr/bin/env python3
"""PROVA VIVA FINAL — Aether Vault 0xc937: autossuficiente em gas (cofre reembolsa o deployer).
Chaves persistidas em KEYS.json antes de qualquer acao (a prova pode ser retomada)."""
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

# chaves persistentes
if (HERE / "KEYS.json").exists():
    K = json.loads((HERE / "KEYS.json").read_text())
    m3b = Account.from_key(K["m3b"]); heirb2 = Account.from_key(K["heirb2"])
    print("chaves reutilizadas de KEYS.json")
else:
    m3b, heirb2 = Account.create(), Account.create()
    (HERE / "KEYS.json").write_text(json.dumps({"m3b": m3b.key.hex(), "heirb2": heirb2.key.hex()}, indent=1))
    print("chaves novas salvas em KEYS.json")

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

print(f"cofre: {vault.functions.ethBalance().call()} wei | deployer: {w3.eth.get_balance(DEPLOYER.address)} wei")

p("A. Retomada: proposta 2 pendente (threshold 1) -> aprova -> executa")
print(f"approve {txh(send(DEPLOYER, vault.functions.approveProposal(2)))}")
print(f"execute {txh(send(DEPLOYER, vault.functions.executeProposal(2, b'')))}")
print(f"deployer agora: {w3.eth.get_balance(DEPLOYER.address)} wei")

p("B. Papeis: m3b (admin novo), heirb2 (membro com limites)")
raw(DEPLOYER, m3b.address, 40000000000000)
raw(DEPLOYER, heirb2.address, 40000000000000)
print(f"add m3b {txh(send(DEPLOYER, vault.functions.addMember(m3b.address, 50000000000000, 100000000000000)))}")
print(f"add heirb2 {txh(send(DEPLOYER, vault.functions.addMember(heirb2.address, 30000000000000, 60000000000000)))}")
print(f"promote m3b {txh(send(DEPLOYER, vault.functions.promoteMember(m3b.address)))}")
print(f"setThreshold(2) {txh(send(DEPLOYER, vault.functions.setThreshold(2)))}")
print(f"admins={vault.functions.activeAdminCount().call()} threshold={vault.functions.threshold().call()}")

p("C. Multisig 2-de-2: proposta -> cedo bloqueia -> 2 aprovacoes -> executa")
print(f"propose(m3b) 0.00005 p/ heirb2 {txh(send(m3b, vault.functions.proposeSpend(heirb2.address, 50000000000000, 60, False)))}")
must_revert("executar com 0/2", m3b, vault.functions.executeProposal(3, b""))
print(f"approve(m3b) {txh(send(m3b, vault.functions.approveProposal(3)))}")
print(f"approve(deployer) {txh(send(DEPLOYER, vault.functions.approveProposal(3)))}")
print(f"execute(heirb2) {txh(send(heirb2, vault.functions.executeProposal(3, b'')))}")

p("C2. Recarga do cofre: deposito 0.00012 ETH")
print(f"deposit {txh(send(DEPLOYER, vault.functions.deposit(), value=120000000000000))}")
print(f"ethBalance = {vault.functions.ethBalance().call()} wei")

p("D. Gasto sob limite (heirb2, 0.00001) + acima do limite bloqueia")
print(f"withdraw {txh(send(heirb2, vault.functions.withdrawUnderLimit(heirb2.address, 10000000000000)))}")
must_revert("acima do limite diario", heirb2, vault.functions.withdrawUnderLimit(heirb2.address, 200000000000000))

p("E. Stream 0.00004 em 180s + claim parcial")
print(f"createStream {txh(send(DEPLOYER, vault.functions.createStream(heirb2.address, 40000000000000, 180)))}")
time.sleep(8)
print(f"claim parcial {txh(send(heirb2, vault.functions.withdrawStream(0)))}")

p("F. checkIn + heranca (gracia 5s)")
print(f"checkIn {txh(send(DEPLOYER, vault.functions.checkIn()))}")
print(f"setHeir {txh(send(DEPLOYER, vault.functions.setHeir(heirb2.address, 5)))}")
must_revert("claim antes da gracia", heirb2, vault.functions.claimAsHeir())
time.sleep(6)
print(f"claim {txh(send(heirb2, vault.functions.claimAsHeir()))}")
print(f"heirb2 e o novo owner? {vault.functions.owner().call() == heirb2.address}")

p("G. Emergencia: freeze -> bloqueia -> timelock -> unfreeze")
print(f"freeze {txh(send(heirb2, vault.functions.emergencyFreeze(1)))}")
must_revert("withdraw sob freeze", heirb2, vault.functions.withdrawUnderLimit(heirb2.address, 1000000000000))
must_revert("unfreeze antes do timelock", heirb2, vault.functions.unfreeze())
time.sleep(62)
print(f"unfreeze {txh(send(heirb2, vault.functions.unfreeze()))}")

p("H. Reciclagem parcial p/ o mock")
raw(heirb2, DEPLOYER.address, w3.eth.get_balance(heirb2.address) - 30000000000000)

p("I. Yield: MockStrategy 10%")
mock = w3.eth.contract(abi=mock_art["abi"], bytecode=mock_art["bytecode"]["object"])
rc = send(DEPLOYER, mock.constructor(w3.to_checksum_address(CA)), gas=1200000)
MOCK = w3.to_checksum_address(rc["contractAddress"])
print(f"mock {txh(rc)}")
print(f"setStrategy {txh(send(heirb2, vault.functions.setStrategy(MOCK)))}")
antes = vault.functions.ethBalance().call()
print(f"deployToStrategy {txh(send(heirb2, vault.functions.deployToStrategy(20000000000000)))}")
print(f"harvest {txh(send(heirb2, vault.functions.harvestFromStrategy(20000000000000)))}")
print(f"rendimento = +{vault.functions.ethBalance().call() - antes} wei (yield 10%)")

p("J. Reciclagem final")
for a in (m3b, heirb2):
    try: raw(a, DEPLOYER.address, w3.eth.get_balance(a.address) - 30000000000000)
    except Exception as e: print(f"  parcial: {str(e)[:60]}")

p("RESUMO")
print(f"Contrato: {CA}")
print(f"{len(H)} txs desta rodada:")
for h in H: print("  https://sepolia.arbiscan.io/tx/" + h)
prev = json.loads((HERE / "PROOF_HASHES.json").read_text()) if (HERE / "PROOF_HASHES.json").exists() else {"contract": CA, "hashes": []}
(HERE / "PROOF_HASHES.json").write_text(json.dumps({"contract": CA, "hashes": prev["hashes"] + H}, indent=1))
print("PROOF_HASHES.json atualizado")
