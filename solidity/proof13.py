#!/usr/bin/env python3
import json
from pathlib import Path
from web3 import Web3
from eth_account import Account
RPC = "https://sepolia-rollup.arbitrum.io/rpc"
w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
HERE = Path(__file__).parent
CA = "0xc937f1e44d037D5AcAC6e7f1016698650f900B19"
MOCK = "0x66B4fDC7Dd6D7Ab12C7F3317e6235FE05576b670"
abi = json.loads((HERE / "out" / "AetherVault.sol" / "AetherVault.json").read_text())["abi"]
vault = w3.eth.contract(address=w3.to_checksum_address(CA), abi=abi)
DEPLOYER = Account.from_key("0xc5c66dff1c3cfae98bea54fc80598a69f680e2d83c22105ebff02c9ca87934bf")
H = []
def txh(r):
    H.append(r["transactionHash"].hex()); return f"tx https://sepolia.arbiscan.io/tx/{r['transactionHash'].hex()}"
def send(fn, value=0, gas=None):
    g = {"gas": gas or 350000, "maxFeePerGas": w3.to_wei(0.05, "gwei"), "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei")}
    t = fn.build_transaction({"from": DEPLOYER.address, "nonce": w3.eth.get_transaction_count(DEPLOYER.address, "pending"),
                              "chainId": w3.eth.chain_id, "value": value, **g})
    h = w3.eth.send_raw_transaction(DEPLOYER.sign_transaction(t).raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=90)
    assert r["status"] == 1, f"REVERTIDA: {h.hex()}"
    return r
print("=== I2. Ciclo de yield completo (segunda alocacao da lastro ao rendimento) ===")
print(f"deployToStrategy(0.000015) {txh(send(vault.functions.deployToStrategy(15000000000000)))}")
antes = vault.functions.ethBalance().call()
print(f"harvest(0.000015) {txh(send(vault.functions.harvestFromStrategy(15000000000000)))}")
print(f"rendimento = +{vault.functions.ethBalance().call() - antes} wei (yield 10% simulado)")
print(f"ethBalance final: {vault.functions.ethBalance().call()} wei | strategyBalance: {vault.functions.strategyBalance().call()}")
prev = json.loads((HERE / "PROOF_HASHES.json").read_text())
(HERE / "PROOF_HASHES.json").write_text(json.dumps({"contract": CA, "hashes": prev["hashes"] + H}, indent=1))
print(f"{len(H)} txs somadas")
