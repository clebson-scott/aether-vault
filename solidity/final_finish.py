#!/usr/bin/env python3
"""FINAL FINISH: varre saldo das contas de teste -> unfreeze -> deploy completo da v2."""
import json, subprocess, sys
from pathlib import Path
from web3 import Web3
from eth_account import Account

RPC = "https://sepolia-rollup.arbitrum.io/rpc"
w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
HERE = Path(__file__).parent
DEPLOYER = Account.from_key("0xc5c66dff1c3cfae98bea54fc80598a69f680e2d83c22105ebff02c9ca87934bf")

# 1. varre contas de teste com sobra (m3b, heirb2 do KEYS.json)
try:
    K = json.loads((HERE / "KEYS.json").read_text())
    for name, keyhex in K.items():
        a = Account.from_key(keyhex)
        b = w3.eth.get_balance(a.address)
        if b > 30000000000000:
            t = {"from": a.address, "to": DEPLOYER.address, "value": b - 30000000000000,
                 "nonce": w3.eth.get_transaction_count(a.address, "pending"),
                 "chainId": w3.eth.chain_id, "gas": 30000,
                 "maxFeePerGas": w3.to_wei(0.025, "gwei"), "maxPriorityFeePerGas": w3.to_wei(0.001, "gwei")}
            w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(a.sign_transaction(t).raw_transaction), timeout=60)
            print(f"varrido {name}: +{b}")
except Exception as e:
    print("varredura parcial:", e)
print("deployer apos varredura:", w3.eth.get_balance(DEPLOYER.address))

# 2. unfreeze do vault antigo (se ainda congelado)
r = subprocess.run([sys.executable, str(HERE / "unfreeze_final.py")], capture_output=True, text=True, timeout=180)
print(r.stdout[-600:])
if r.returncode != 0: print("unfreeze erro:", r.stderr[-200:])

# 3. deploy v2 completo
r = subprocess.run([sys.executable, str(HERE / "deploy_v2.py")], capture_output=True, text=True, timeout=900)
print(r.stdout[-3000:])
if r.returncode != 0: print("deploy_v2 erro:", r.stderr[-500:])
