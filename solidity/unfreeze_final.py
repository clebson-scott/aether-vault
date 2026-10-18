#!/usr/bin/env python3
"""Envia o unfreeze apos o timelock expirar e prova que o cofre voltou (deployer = admin)."""
import json
from pathlib import Path
from web3 import Web3
from eth_account import Account
RPC = "https://sepolia-rollup.arbitrum.io/rpc"
w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
HERE = Path(__file__).parent
CA = "0xc937f1e44d037D5AcAC6e7f1016698650f900B19"
abi = json.loads((HERE / "ABI_AetherVault.json").read_text())
vault = w3.eth.contract(address=w3.to_checksum_address(CA), abi=abi)
DEPLOYER = Account.from_key("os.environ.get("DEPLOYER_KEY")")
print("frozen:", vault.functions.frozen().call(), "| freezeUntil:", vault.functions.freezeUntil().call())
def send(fn, gas=350000):
    t = fn.build_transaction({"from": DEPLOYER.address, "nonce": w3.eth.get_transaction_count(DEPLOYER.address, "pending"),
        "chainId": w3.eth.chain_id, "gas": gas, "maxFeePerGas": w3.to_wei(0.05, "gwei"), "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei")})
    h = w3.eth.send_raw_transaction(DEPLOYER.sign_transaction(t).raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=90)
    assert r["status"] == 1, f"revert: {h.hex()}"
    return "https://sepolia.arbiscan.io/tx/" + h.hex()
if w3.eth.get_balance(DEPLOYER.address) < 10000000000000:
    print("sem gas p/ unfreeze; peça ao dono")
else:
    print("unfreeze tx:", send(vault.functions.unfreeze()))
    print("frozen agora:", vault.functions.frozen().call())
