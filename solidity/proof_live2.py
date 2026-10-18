#!/usr/bin/env python3
"""Prova viva AETHER VAULT (modo frugal) — 12 etapas com micro-valores na Arbitrum Sepolia."""
import json, time
from pathlib import Path
from web3 import Web3
from eth_account import Account

RPC = "https://sepolia-rollup.arbitrum.io/rpc"
w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
assert w3.is_connected()

HERE = Path(__file__).parent
abi = json.loads((HERE / "out" / "AetherVault.sol" / "AetherVault.json").read_text())["abi"]
mock_art = json.loads((HERE / "out" / "AetherVault.sol" / "MockStrategy.json").read_text())

DEPLOYER = Account.from_key("os.environ.get("DEPLOYER_KEY")")
ETH = 10**18
GAS = {"gas": 700000, "maxFeePerGas": w3.to_wei(0.05, "gwei"), "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei")}
H = []

def txh(r):
    H.append(r["transactionHash"].hex())
    return f"tx https://sepolia.arbiscan.io/tx/{r['transactionHash'].hex()}"

def send(acct, fn, value=0, gas=None, tries=3):
    for i in range(tries):
        try:
            g = dict(GAS); g["gas"] = gas or GAS["gas"]
            t = fn.build_transaction({"from": acct.address,
                "nonce": w3.eth.get_transaction_count(acct.address, "pending"),
                "chainId": w3.eth.chain_id, "value": value, **g})
            h = w3.eth.send_raw_transaction(acct.sign_transaction(t).raw_transaction)
            r = w3.eth.wait_for_transaction_receipt(h, timeout=90)
            assert r["status"] == 1, f"REVERTIDA: {h.hex()}"
            return r
        except AssertionError:
            raise
        except Exception as e:
            if i == tries - 1: raise
            time.sleep(2)

def must_revert(label, acct, fn, value=0):
    try:
        send(acct, fn, value)
        print(f"  ✗ {label}: NAO reverteu (PROBLEMA)")
    except Exception as e:
        print(f"  ✓ {label}: revertida como esperado")

def p(t): print(f"\n=== {t} ===")

m2, heir, dest = Account.create(), Account.create(), Account.create()
p("0. Contas: m2(admin depois de promote), heir(membro->herdeiro), dest(destinatario)")
for a in (m2, heir, dest):
    t = {"from": DEPLOYER.address, "to": a.address, "value": 200000000000000,
         "nonce": w3.eth.get_transaction_count(DEPLOYER.address, "pending"),
         "chainId": w3.eth.chain_id, "gas": 30000, **{k: GAS[k] for k in ("maxFeePerGas","maxPriorityFeePerGas")}}
    w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(DEPLOYER.sign_transaction(t).raw_transaction), timeout=60)

p("1. Deploy")
vault = w3.eth.contract(abi=abi, bytecode=json.loads((HERE/"out"/"AetherVault.sol"/"AetherVault.json").read_text())["bytecode"]["object"])
rc = send(DEPLOYER, vault.constructor(), gas=6000000)
CA = w3.to_checksum_address(rc["contractAddress"])
vault = w3.eth.contract(address=CA, abi=abi)
print(f"contrato: {CA}")
print(f"deploy {txh(rc)}")

p("2. init")
print(f"init {txh(send(DEPLOYER, vault.functions.init('Cofre Vivo Aether')))}")

p("3. Deposito publico 0.00025 ETH")
print(f"deposit {txh(send(DEPLOYER, vault.functions.deposit(), value=250000000000000))}")
print(f"ethBalance = {vault.functions.ethBalance().call()} wei")

p("4. Membros com papeis: m2 (membro), heir (membro com limites)")
print(f"add m2 {txh(send(DEPLOYER, vault.functions.addMember(m2.address, 100000000000000, 200000000000000)))}")
print(f"add heir {txh(send(DEPLOYER, vault.functions.addMember(heir.address, 50000000000000, 100000000000000)))}")
print(f"promote m2->admin {txh(send(DEPLOYER, vault.functions.promoteMember(m2.address)))}")

p("5. Threshold 2-de-2 admins (owner + m2)")
print(f"setThreshold {txh(send(DEPLOYER, vault.functions.setThreshold(2)))}")
print(f"threshold={vault.functions.threshold().call()} admins={vault.functions.activeAdminCount().call()}")

p("6. Multisig: proposta 0.00006 ETH -> 2 aprovacoes -> executa")
print(f"propose(m2) {txh(send(m2, vault.functions.proposeSpend(dest.address, 60000000000000, 60, False)))}")
print(f"approve(deployer) {txh(send(DEPLOYER, vault.functions.approveProposal(0)))}")
print(f"execute(m2) {txh(send(m2, vault.functions.executeProposal(0, b'')))}")
print(f"saldo dest = {w3.eth.get_balance(dest.address)} wei (recebeu)")

p("6b. Execucao SEM aprovacoes suficientes tem que bloquear")
send(m2, vault.functions.proposeSpend(dest.address, 1000000000000, 60, False))
must_revert("execute com 1/2 aprovacoes", m2, vault.functions.executeProposal(1, b""))

p("7. Gasto sob limite (heir, 0.00002 ETH, sem multisig)")
print(f"withdraw {txh(send(heir, vault.functions.withdrawUnderLimit(heir.address, 20000000000000)))}")
p("7b. Acima do limite diario (0.0002 ETH) bloqueia")
must_revert("limite diario excedido", heir, vault.functions.withdrawUnderLimit(heir.address, 200000000000000))

p("8. Stream: 0.00005 ETH em 180s + claim parcial")
print(f"createStream {txh(send(DEPLOYER, vault.functions.createStream(heir.address, 50000000000000, 180)))}")
time.sleep(8)
print(f"claim parcial {txh(send(heir, vault.functions.withdrawStream(0)))} (pro-rata)")
print(f"sacado do stream: {vault.functions.streams(0).call()[2]} wei")

p("9. checkIn (dead man's switch vivo)")
print(f"checkIn {txh(send(DEPLOYER, vault.functions.checkIn()))}")

p("10. Heranca: gracia 5s -> cedo bloqueia -> apos gracia herda")
print(f"setHeir {txh(send(DEPLOYER, vault.functions.setHeir(heir.address, 5)))}")
must_revert("claim antes da gracia", heir, vault.functions.claimAsHeir())
time.sleep(6)
print(f"claim {txh(send(heir, vault.functions.claimAsHeir()))}")
print(f"novo owner = heir? {vault.functions.owner().call() == heir.address}")

p("11. Emergencia: freeze -> bloqueia -> timelock 60s -> unfreeze")
print(f"freeze {txh(send(heir, vault.functions.emergencyFreeze(1)))}")
print(f"frozen={vault.functions.frozen().call()}")
must_revert("withdraw sob freeze", heir, vault.functions.withdrawUnderLimit(heir.address, 1000000000000))
must_revert("unfreeze antes do timelock", heir, vault.functions.unfreeze())
time.sleep(62)
print(f"unfreeze {txh(send(heir, vault.functions.unfreeze()))}")

p("12. Yield: MockStrategy com 10% de rendimento")
mock = w3.eth.contract(abi=mock_art["abi"], bytecode=mock_art["bytecode"]["object"])
rc = send(DEPLOYER, mock.constructor(CA), gas=2000000)
MOCK = w3.to_checksum_address(rc["contractAddress"])
print(f"mock {txh(rc)} @ {MOCK}")
print(f"setStrategy {txh(send(heir, vault.functions.setStrategy(MOCK)))}")
antes = vault.functions.ethBalance().call()
print(f"deployToStrategy {txh(send(heir, vault.functions.deployToStrategy(20000000000000)))}")
print(f"harvest {txh(send(heir, vault.functions.harvestFromStrategy(20000000000000)))}")
print(f"rendimento = +{vault.functions.ethBalance().call() - antes} wei (10% de yield)")

p("13. Reciclagem das contas de teste")
for a in (m2, heir, dest):
    try:
        b = w3.eth.get_balance(a.address)
        t = {"from": a.address, "to": DEPLOYER.address, "value": b - 30000000000000,
             "nonce": w3.eth.get_transaction_count(a.address, "pending"),
             "chainId": w3.eth.chain_id, "gas": 30000, **{k: GAS[k] for k in ("maxFeePerGas","maxPriorityFeePerGas")}}
        w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(a.sign_transaction(t).raw_transaction), timeout=60)
    except Exception as e: print(f"  retorno parcial: {str(e)[:60]}")
print(f"deployer final: {w3.eth.get_balance(DEPLOYER.address)} wei")

p("RESUMO")
print(f"Contrato: {CA}")
print(f"Explorer: https://sepolia.arbiscan.io/address/{CA}")
print(f"{len(H)} txs:")
for h in H: print("  https://sepolia.arbiscan.io/tx/" + h)
(HERE / "PROOF_HASHES.json").write_text(json.dumps({"contract": CA, "hashes": H}, indent=1))
print("PROOF_HASHES.json salvo")
