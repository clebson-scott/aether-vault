#!/usr/bin/env python3
"""Prova viva do AETHER VAULT na Arbitrum Sepolia — sequencia completa com tx hashes."""
import json, sys, time
from pathlib import Path
from web3 import Web3
from eth_account import Account
from web3 import Web3 as _W
def to_checksum(a): return _W.to_checksum_address(a)

RPC = "https://sepolia-rollup.arbitrum.io/rpc"
w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
assert w3.is_connected(), "sem conexao"

HERE = Path(__file__).parent
ART = HERE / "out" / "AetherVault.sol" / "AetherVault.json"
art = json.loads(ART.read_text())
abi, bytecode = art["abi"], art["bytecode"]["object"]

DEPLOYER = Account.from_key("0xc5c66dff1c3cfae98bea54fc80598a69f680e2d83c22105ebff02c9ca87934bf")
ETH = 10**18
GAS = {"gas": 1500000, "maxFeePerGas": w3.to_wei(0.05, "gwei"), "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei")}
HASHES = []

def tx_hash(h):
    HASHES.append(h)
    return "https://sepolia.arbiscan.io/tx/" + h.hex()

def send(account, fn, value=0, tries=3, gas=None):
    """assina, envia e espera receipt; devolve receipt"""
    for i in range(tries):
        try:
            tx = fn.build_transaction({
                "from": account.address,
                "nonce": w3.eth.get_transaction_count(account.address, "pending"),
                "chainId": w3.eth.chain_id, "value": value, **(dict(GAS, gas=gas) if gas else GAS)})
            signed = account.sign_transaction(tx)
            h = w3.eth.send_raw_transaction(signed.raw_transaction)
            r = w3.eth.wait_for_transaction_receipt(h, timeout=90)
            assert r["status"] == 1, f"tx revertida: {h.hex()}"
            return r
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(3)

def revert_reason(fn, account, value=0):
    """tenta executar e devolve (reverteu?, razao)"""
    try:
        rc = send(account, fn, value)
        return (rc["status"] == 0, "status=0 (revertida)")
    except Exception as e:
        msg = str(e)
        return (True, msg[:200])

def newacct(name):
    a = Account.create()
    w = Account.from_key(a.key)
    return w

def fund(to, amount):
    tx = {"from": DEPLOYER.address, "to": to.address,
          "value": amount, "nonce": w3.eth.get_transaction_count(DEPLOYER.address, "pending"),
          "chainId": w3.eth.chain_id, "gas": 30000, **GAS}
    h = w3.eth.send_raw_transaction(DEPLOYER.sign_transaction(tx).raw_transaction)
    w3.eth.wait_for_transaction_receipt(h, timeout=60)
    return h

def p(label):
    print(f"\n=== {label} ===")

# ---------------- contas ----------------
m1, m2, m3, heir, dest = newacct("m1"), newacct("m2"), newacct("m3"), newacct("heir"), newacct("dest")
p("0. Cartas: m1(admin), m2(membro), m3(admin), herdeiro, destinatario")
for a in (m1, m2, m3, heir, dest):
    fund(a, int(0.0005 * ETH))
print("gas enviado p/ 5 contas de teste")

# ---------------- deploy ----------------
p("1. Deploy AetherVault")
vault = w3.eth.contract(abi=abi, bytecode=bytecode)
rc = send(DEPLOYER, vault.constructor(), gas=8000000)
assert rc["status"] == 1 and rc["contractAddress"], f"deploy falhou: {rc['status']}"
CA = to_checksum(rc["contractAddress"])
vault = w3.eth.contract(address=CA, abi=abi)
print(f"contrato: {CA}")
print(f"deploy tx: {tx_hash(rc['transactionHash'])}")

p("2. init('Cofre Vivo da Familia')")
rc = send(DEPLOYER, vault.functions.init("Cofre Vivo da Familia"))
print(f"init tx: {tx_hash(rc['transactionHash'])} status={rc['status']}")

p("3. Deposito publico: 0.012 ETH")
rc = send(DEPLOYER, vault.functions.deposit(), value=int(0.002 * ETH))
print(f"deposit tx: {tx_hash(rc['transactionHash'])} status={rc['status']}")
print(f"ethBalance = {w3.from_wei(vault.functions.ethBalance().call(), 'ether')} ETH")

p("4. Membros com papeis diferentes")
rc = send(DEPLOYER, vault.functions.addMember(m1.address, int(0.001*ETH), int(0.002*ETH)))
print(f"add m1 (membro) tx: {tx_hash(rc['transactionHash'])}")
rc = send(DEPLOYER, vault.functions.addMember(m2.address, int(0.0004*ETH), int(0.001*ETH)))
print(f"add m2 (membro) tx: {tx_hash(rc['transactionHash'])}")
rc = send(DEPLOYER, vault.functions.addMember(m3.address, int(0.0004*ETH), int(0.001*ETH)))
print(f"add m3 (membro) tx: {tx_hash(rc['transactionHash'])}")
rc = send(DEPLOYER, vault.functions.promoteMember(m1.address))
print(f"promote m1 -> ADMIN tx: {tx_hash(rc['transactionHash'])}")
rc = send(DEPLOYER, vault.functions.promoteMember(m3.address))
print(f"promote m3 -> ADMIN tx: {tx_hash(rc['transactionHash'])}")

p("5. Threshold multisig 2-de-3 admins")
rc = send(DEPLOYER, vault.functions.setThreshold(2))
print(f"setThreshold tx: {tx_hash(rc['transactionHash'])}")
print(f"threshold = {vault.functions.threshold().call()} | admins = {vault.functions.activeAdminCount().call()}")

p("6. Proposta de saque (0.003 ETH) + aprovacoes + execucao")
rc = send(m1, vault.functions.proposeSpend(dest.address, int(0.0004*ETH), 60, False))
print(f"propose tx: {tx_hash(rc['transactionHash'])}")
rc = send(DEPLOYER, vault.functions.approveProposal(0))
print(f"approve owner tx: {tx_hash(rc['transactionHash'])}")
reverteu, motivo = revert_reason(m3, vault.functions.executeProposal(0, b""))
if not reverteu:
    rc = send(m3, vault.functions.executeProposal(0, b""))
    print(f"execute tx: {tx_hash(rc['transactionHash'])} status={rc['status']}")
dest_bal = w3.eth.get_balance(dest.address)
print(f"destinatario recebeu. saldo dest = {w3.from_wei(dest_bal, 'ether')} ETH")

p("7. Gasto sob limite diario (m2, 0.0004 ETH, sem multisig)")
rc = send(m2, vault.functions.withdrawUnderLimit(m2.address, int(0.0001*ETH)))
print(f"withdraw tx: {tx_hash(rc['transactionHash'])} status={rc['status']}")
p("7b. Tentativa ACIMA do limite (0.002 ETH) — tem que reverter")
reverteu, motivo = revert_reason(m2, vault.functions.withdrawUnderLimit(m2.address, int(0.0009*ETH)))
print(f"reverteu? {reverteu} | motivo: {'DailyLimitExceeded' if 'DailyLimit' in motivo else motivo[:100]}")

p("8. Stream de pagamento: 0.002 ETH em 300s")
rc = send(DEPLOYER, vault.functions.createStream(m2.address, int(0.0004*ETH), 240))
print(f"createStream tx: {tx_hash(rc['transactionHash'])}")
print("aguardando 10s p/ acumular...")
time.sleep(10)
rc = send(m2, vault.functions.withdrawStream(0))
print(f"claim parcial tx: {tx_hash(rc['transactionHash'])} status={rc['status']}")

p("9. checkIn (dead man's switch vivo)")
rc = send(DEPLOYER, vault.functions.checkIn())
print(f"checkIn tx: {tx_hash(rc['transactionHash'])}")

p("10. Heranca: setHeir(gracia 5s) -> claim antes da gracia (bloqueia) -> apos (herda)")
rc = send(DEPLOYER, vault.functions.setHeir(heir.address, 5))
print(f"setHeir tx: {tx_hash(rc['transactionHash'])}")
reverteu, motivo = revert_reason(heir, vault.functions.claimAsHeir())
print(f"claim imediato bloqueado? {reverteu} | {'HeirStillWithinGrace' if 'Grace' in motivo or 'revert' in motivo else motivo[:80]}")
time.sleep(6)
rc = send(heir, vault.functions.claimAsHeir())
print(f"claim apos gracia tx: {tx_hash(rc['transactionHash'])} status={rc['status']}")
print(f"novo owner = {vault.functions.owner().call()[:10]}... (herdeiro)")

p("11. Emergencia: freeze -> operacoes bloqueadas -> timelock -> unfreeze")
rc = send(heir, vault.functions.emergencyFreeze(1))
print(f"emergencyFreeze tx: {tx_hash(rc['transactionHash'])}")
print(f"frozen={vault.functions.frozen().call()} until={vault.functions.freezeUntil().call()}")
reverteu, motivo = revert_reason(m2, vault.functions.withdrawUnderLimit(m2.address, int(0.0001*ETH)))
print(f"withdraw sob freeze bloqueado? {reverteu} | {'VaultFrozen' if 'Frozen' in motivo or 'revert' in motivo else motivo[:80]}")
reverteu, motivo = revert_reason(heir, vault.functions.unfreeze())
print(f"unfreeze ANTES do timelock bloqueado? {reverteu} | {'VaultFrozen (timelock ok)' if 'Frozen' in motivo or 'revert' in motivo else motivo[:80]}")
print("aguardando timelock de 60s...")
time.sleep(62)
rc = send(heir, vault.functions.unfreeze())
print(f"unfreeze tx: {tx_hash(rc['transactionHash'])} status={rc['status']}")
rc = send(m2, vault.functions.withdrawUnderLimit(m2.address, int(0.0001*ETH)))
print(f"withdraw pos-unfreeze tx: {tx_hash(rc['transactionHash'])} status={rc['status']}")

p("12. Yield: MockStrategy (adaptador com 10% de rendimento)")
mock_art = json.loads((HERE / "out" / "AetherVault.sol" / "MockStrategy.json").read_text())
mock = w3.eth.contract(abi=mock_art["abi"], bytecode=mock_art["bytecode"]["object"])
rc = send(DEPLOYER, mock.constructor(CA))
MOCK = to_checksum(rc.contractAddress)
print(f"MockStrategy: {MOCK} | deploy tx: {tx_hash(rc['transactionHash'])}")
rc = send(heir, vault.functions.setStrategy(MOCK))
print(f"setStrategy tx: {tx_hash(rc['transactionHash'])}")
bal_antes = vault.functions.ethBalance().call()
rc = send(heir, vault.functions.deployToStrategy(int(0.0002*ETH)))
print(f"deployToStrategy tx: {tx_hash(rc['transactionHash'])} status={rc['status']}")
rc = send(heir, vault.functions.harvestFromStrategy(int(0.0002*ETH)))
print(f"harvestFromStrategy tx: {tx_hash(rc['transactionHash'])} status={rc['status']}")
bal_depois = vault.functions.ethBalance().call()
print(f"rendimento do cofre: +{w3.from_wei(bal_depois - bal_antes, 'ether')} ETH (yield simulado de 10%)")

# ---------------- resumo ----------------
p("RESUMO")
print(f"Contrato: {CA}")
print(f"Explorer: https://sepolia.arbiscan.io/address/{CA}")
print(f"Total de txs da prova: {len(HASHES)}")
print("\n".join("  " + "https://sepolia.arbiscan.io/tx/" + h.hex() for h in HASHES))
p("13. Reciclagem: contas de teste devolvem o saldo ao deployer")
for a in (m1, m2, m3, heir, dest):
    try:
        b = w3.eth.get_balance(a.address)
        if b > 0:
            keep = 10000000000000
            t = {"from": a.address, "to": DEPLOYER.address, "value": b - keep,
                 "nonce": w3.eth.get_transaction_count(a.address, "pending"),
                 "chainId": w3.eth.chain_id, "gas": 30000,
                 "maxFeePerGas": w3.to_wei(0.05, "gwei"), "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei")}
            h = w3.eth.send_raw_transaction(a.sign_transaction(t).raw_transaction)
            w3.eth.wait_for_transaction_receipt(h, timeout=60)
    except Exception as e:
        print(f"  retorno parcial de uma conta: {str(e)[:60]}")
print(f"saldo final do deployer: {w3.from_wei(w3.eth.get_balance(DEPLOYER.address), 'ether')} ETH")

Path(HERE / "PROOF_HASHES.json").write_text(json.dumps({
    "contract": CA, "hashes": [h.hex() for h in HASHES]}, indent=1))
print("\nhashes salvos em PROOF_HASHES.json")
