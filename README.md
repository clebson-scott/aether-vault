# AETHER VAULT — Living Shared Vaults (Cofres Vivos Compartilhados)

> "Você não manda só pra uma carteira. Você manda pra um Cofre Vivo." — spec original

O dinheiro cai num smart contract controlado pela carteira, com regras que você define.
O cofre pode ser só seu, compartilhado com 2, 10 ou 10.000 pessoas, ou público
(qualquer um deposita). O dinheiro nunca "sai" da estrutura — só muda de estado,
e trabalha rendendo enquanto fica parado.

## Funcionalidades (todas provadas ao vivo na Arbitrum Sepolia)

| # | Funcionalidade | Estado na prova viva |
|---|---|---|
| 1 | Depósito público (cofre comunitário) | ✅ tx on-chain |
| 2 | Membros com papéis (member/admin), remoção | ✅ |
| 3 | Multisig dinâmico M-de-N (threshold ajustável) | ✅ 2-de-2 e 2-de-4 executado |
| 4 | Executar sem aprovações suficientes → bloqueia | ✅ revert `InsufficientApprovals(1,2)` |
| 5 | Limite diário/semanal rolante por pessoa | ✅ saque ok + excedente bloqueado |
| 6 | Streaming de pagamento (pro-rata por segundo) | ✅ criação + claim parcial |
| 7 | Dead man's switch (checkIn) + herança automática | ✅ gracia respeitada, herdeiro vira owner |
| 8 | Modo emergência (freeze + timelock) | ✅ freeze bloqueia tudo; unfreeze cedo reverte |
| 9 | Porta condicional via oráculo (interface IOracleGate) | 🧩 interface pronta (padrão ZEUS GUARD) |
| 10 | Adaptador de yield encaixável (IStrategy) | ✅ MockStrategy +10% colhido |

## Endereço e prova

- **Contrato (Arbitrum Sepolia):** `0xc937f1e44d037D5AcAC6e7f1016698650f900B19`
- **Explorer:** https://sepolia.arbiscan.io/address/0xc937f1e44d037D5AcAC6e7f1016698650f900B19
- **Hashes da prova (36 txs):** `solidity/PROOF_ALL_HASHES.json`
- **ABI:** `solidity/ABI_AetherVault.json`
- **Deployer:** `0x134fb02Ee3aB7E03D6Ac231ca46b9445573C634b`

## Duas portas, um contrato

1. **`src/` — Rust/Stylus (SDK 0.10.9)**: o core original, 8/8 testes unit.
   ⚠️ A Arbitrum pausou ativações Stylus na Sepolia (out/2026 — até o ZEUS GUARD
   falha o check). O contrato está pronto; deploy quando as ativações reabriram.
2. **`solidity/src/AetherVault.sol` — porta Solidity (v1.2)**: mesma lógica,
   deployada e provada ao vivo. É a referência de produção.

## Bugs reais encontrados pela prova viva (e corrigidos)

1. **Herança bloqueada para herdeiro já-membro** (v1.0): `claimAsHeir` chamava
   `_addMember` e revertia `MemberExists` quando o herdeiro já era membro do
   cofre — caso comum (herdeiro = familiar que já usa o cofre).
   **Fix v1.1:** promove para admin se já é membro.
2. **Duração do freeze inflada** (v1.1): `MIN_FREEZE` (60 s) era comparado contra
   MINUTOS → congelava 1 hora em vez de 1 minuto.
   **Fix v1.2:** `secs = max(minutes*60, MIN_FREEZE)`.
   Ambos corrigidos nas DUAS portas (Solidity e Rust).

## Como interagir (foundry)

```bash
RPC=https://sepolia-rollup.arbitrum.io/rpc
CA=0xc937f1e44d037D5AcAC6e7f1016698650f900B19
cast call $CA "vaultInfo()" --rpc-url $RPC
cast send $CA "deposit()" --value 0.001ether --rpc-url $RPC --private-key $KEY
cast send $CA "addMember(address,uint256,uint256)" 0xMEMBRO 1000000000000 3000000000000 \
  --rpc-url $RPC --private-key $KEY
cast send $CA "createStream(address,uint256,uint64)" 0xBENEF 1000000000000 86400 \
  --rpc-url $RPC --private-key $KEY
```

Scripts de prova: `solidity/proof*.py` (sequência completa com hashes e asserts).
Chaves de teste do vault: `solidity/KEYS.json` (NÃO usar em produção — testnet).

## Segurança — pontos de atenção

- Contabilidade interna própria (`ethBalance`) — nunca confia em `address(this).balance`
- Reentrância: guard em todas as funções que movem valor
- Access control: `onlyAdmin` em gestão, limites por membro, `onlyHeir` na herança
- Timelock no modo emergência (não sai do freeze antes do prazo)
- **Pendente antes de mainnet:** auditoria externa; teste fork da porta Rust na
  reabertura das ativações; adapters reais (Aave/Morpho) no lugar do mock;
  limite de `memberList` (loop em `activeAdminCount` cresce linearmente);
  oráculo de condição não deployed (só a interface e o fluxo de chamada).

## Roadmap (camadas do produto completo)

- [ ] Fábrica de cofres (deploy de cofres filhos a partir de um DAO/multisig)
- [ ] Wallet app: Account Abstraction + passkeys + MPC (camada de produto)
- [ ] Social recovery, simulação de transação, anti-MEV
- [ ] Cross-chain via intents; BTC (Lightning/Runes)
- [ ] Adapters reais de yield (Aave, Morpho, Pendle, Ethena)

---
Autor: Clebson Scott — construído pelo Superagent (Base44), out/2026.
