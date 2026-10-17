#!/usr/bin/env python3
"""Prova viva - continuacao final (proposal 1 pendente com 0 aprovacoes)."""
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

# chaves das rodadas 4 (m2b/heirb) - recriadas? NAO: elas foram geradas em memoria e PERDIDAS
# Solucao: pegar as chaves do proprio proof4 em execucao? Elas se foram.
print("Estado do vault:")
print("  proposalCount:", vault.functions.proposalCount().call())
print("  memberCount:", vault.functions.memberCount().call())
print("  ethBalance:", vault.functions.ethBalance().call())
print("  deployer wei:", w3.eth.get_balance(DEPLOYER.address))
