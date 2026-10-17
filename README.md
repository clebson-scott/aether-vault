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

## v2.0 — Camada de Produto (17/10/2026)

### Arquitetura completa

```
┌─────────────────────────────────────────────────────────────┐
│ FRONTEND (frontend/index.html)                              │
│ MetaMask/Rabby · ethers.js · painel completo do cofre       │
└──────────────────────┬──────────────────────────────────────┘
                       │
┌──────────────────────▼──────────────────────────────────────┐
│ VAULT FACTORY (solidity/src/AetherStack.sol)                │
│ createVault(nome, herdeiro, gracia) → novo Cofre Vivo       │
│ registro: vaultsOf(owner), vaultCount()                    │
└───────┬────────────────────────────────────────────────────┘
        │ cria
┌───────▼────────────────────────────────────────────────────┐
│ AETHER VAULT (Core v1.2)                                   │
│ initFor(owner, nome) · deposit · addMember/promote/remove   │
│ multisig M-de-N · limites rolantes · streams pro-rata      │
│ checkIn/herança · freeze+timelock · IStrategy (yield)     │
│ IOracleGate (portas condicionais)                          │
└───────┬──────────────────────┬─────────────────────────────┘
        │                      │
┌───────▼───────────┐   ┌──────▼──────────────────────────────┐
│ CONDITION ORACLE  │   │ YIELD ADAPTER (IStrategy)           │
│ portas condicionais│ │ mock avançado honesto (8% aa, paga  │
│ 2-de-3 signatários│   │ só saldo real). Produção: trocar por│
│ ecrecover nativo  │   │ adapter Aave V3 / Morpho Blue real │
└───────────────────┘   └─────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│ SMART ACCOUNT (AA-minimal, mesmo arquivo AetherStack.sol)   │
│ owner + passkeys + session keys (teto/validade) + social   │
│ recovery 2-de-3 · execute() chama o Vault nativamente      │
│ EntryPoint/paymaster (ERC-4337 completo): PENDENTE         │
└─────────────────────────────────────────────────────────────┘
```

### Como usar a Factory
```bash
cast send $FACTORY "createVault(string,address,uint64)" "Cofre da Equipe" 0xHERDEIRO 604800 --rpc-url $RPC --private-key $K
cast call $FACTORY "vaultsOf(address)" $SEU_ENDERECO --rpc-url $RPC
```

### Como a Account Abstraction se conecta ao Vault
O SmartAccount guarda ETH e chama `execute(enderecoDoVault, valor, calldata)`
para qualquer operação (deposit, propose, approve, checkIn, freeze...).
Chaves de sessão com teto de gasto permitem que o agente de IA (ou um
funcionário) opere o cofre com limites, sem gastar acima. Recuperação
social: 2 de 3 guardians trocam o owner sem seed phrase.

### Como rodar a interface
```bash
cd frontend && python3 -m http.server 8080
# abra http://localhost:8080 — conecte MetaMask na Arbitrum Sepolia
```
(O frontend é um arquivo único, sem build. Configure os endereços da
Factory no topo da página. Funciona direto do repositório.)

### Endereços v2 (Arbitrum Sepolia) — TODOS DEPLOYADOS E PROVADOS

| Contrato | Endereço | Prova |
|---|---|---|
| VaultFactory | `0x8277EF094EdEef248CdA0Fd68bc5af953B01Ba45` | criou o cofre abaixo |
| Cofre via Factory ("Cofre Scott") | `0x47f22989D80ff1F02bb0a3F4103930264488B556` | deposit + yield + porta oracular |
| ConditionOracle (2-de-3) | `0x774fD6D54180B79DA5c64a76F297651d10c93f16` | proposta executada com prova de 2 assinaturas |
| YieldAdapter | `0x0C3eb6A9612A67aDF889EE4881cbbf4b42BFb581` | alocação + harvest on-chain |
| SmartAccount (AA-minimal) | `0x3C1657113FF5EB6B7C54eAfb4Ab5494490C83b15` | deposit no cofre + session key + social recovery 2-de-3 |
| AetherVault Core (prova v1) | `0xc937f1e44d037D5AcAC6e7f1016698650f900B19` | 36 txs da prova viva v1.2 |

Hashes da prova v2: `solidity/DEPLOY_V2.json`. Signatários do oráculo: `solidity/ORACLE_SIGNERS.json` (testnet).

**Status on-chain real:** Factory, Oracle (gate condicional com 2 assinaturas reais),
YieldAdapter (ciclo completo), SmartAccount (deposit, session key, social recovery
confirmada) e o cofre da Factory — tudo executado na Sepolia. O que ainda é só
código: EntryPoint ERC-4337/bundler/paymaster, adapters Aave/Morpho reais e o app mobile.

### Roadmap até mainnet + Play Store
1. **Auditoria externa** dos 4 contratos + fuzzing (echidna/medusa)
2. EntryPoint ERC-4337 real + bundler + paymaster (gas sponsorship com ERC-20)
3. Adapters reais Aave V3 / Morpho Blue + oráculo de preço Chainlink nas condições
4. App mobile React Native (a interface atual vira o esqueleto)
5. Compliance: Termos de uso, KYB para cofres institucionais, LGPD
6. Play Store: beta fechado → revisão do Google (cripto: declaração de
   carteira não-custodial) → rollout gradual
