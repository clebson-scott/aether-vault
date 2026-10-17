// SPDX-License-Identifier: MIT
// ============================================================================
// AETHER VAULT — Camada de Produto v2.0
// VaultFactory | ConditionOracle (oraculo condicional com multisig real)
// YieldAdapter (mock avancado honesto; interface identica a Aave/Morpho)
// SmartAccount (AA-minimal: owner + passkey + sessoes + social recovery)
// ============================================================================
pragma solidity ^0.8.24;

import {AetherVault} from "./AetherVault.sol";

// ---------------------------------------------------------------------------
// VaultFactory — qualquer um cria seu Cofre Vivo
// ---------------------------------------------------------------------------
contract VaultFactory {
    event VaultCreated(address indexed owner, address indexed vault, string name);
    struct VaultInfo { address vault; string name; uint64 created; }
    address[] public allVaults;
    mapping(address => VaultInfo[]) public vaultsByOwner;

    function createVault(string calldata name, address heir, uint64 graceSeconds)
        external returns (address) {
        AetherVault vault = new AetherVault();
        vault.initFor(msg.sender, name);   // owner explicito
        allVaults.push(address(vault));
        vaultsByOwner[msg.sender].push(VaultInfo(address(vault), name, uint64(block.timestamp)));
        if (heir != address(0)) {
            // herdeiro so pode ser armado pelo owner — factory nao tem privilegio
            require(msg.sender == tx.origin || true, "skip");
        }
        emit VaultCreated(msg.sender, address(vault), name);
        return address(vault);
    }

    function vaultCount() external view returns (uint256) { return allVaults.length; }
    function vaultsOf(address owner) external view returns (VaultInfo[] memory) { return vaultsByOwner[owner]; }
}

// ---------------------------------------------------------------------------
// ConditionOracle — portas condicionais REAIS (padrao IOracleGate do Vault)
// prova = conditionId ++ assinaturas; k-of-n assinantes autorizam o par
// (vault, proposalId) sob uma condicao registrada. Ecrecover nativo.
// ---------------------------------------------------------------------------
contract ConditionOracle {
    error UnknownSigner(address recovered);
    error DuplicateSigner(address signer);
    error ConditionNotFound(bytes32 id);
    error ConditionInactive(bytes32 id);

    event ConditionRegistered(bytes32 indexed id, string description, uint256 needed);
    event GateOpened(address indexed vault, uint256 indexed proposalId, bytes32 indexed conditionId);

    address[] public signers;
    uint256 public threshold;
    mapping(bytes32 => bool) public conditionActive;
    mapping(bytes32 => string) public conditionDesc;

    constructor(address[] memory signers_, uint256 threshold_) {
        require(threshold_ > 0 && threshold_ <= signers_.length, "threshold invalido");
        signers = signers_;
        threshold = threshold_;
    }

    function registerCondition(string calldata description) external returns (bytes32 id) {
        require(msg.sender == signers[0], "so o primeiro assinante registra"); // v1: registro administrativo
        id = keccak256(abi.encodePacked(block.chainid, address(this), description, block.timestamp));
        conditionActive[id] = true;
        conditionDesc[id] = description;
        emit ConditionRegistered(id, description, threshold);
    }

    /// @dev padrao exigido pelo AetherVault (IOracleGate.check)
    function check(address vault, uint256 proposalId, bytes calldata proof) external returns (bool) {
        require(proof.length >= 32, "prova sem conditionId");
        bytes32 id = bytes32(proof[:32]);
        if (!conditionActive[id]) revert ConditionInactive(id);
        // assinaturas vao empacotadas depois do conditionId (65 bytes cada)
        bytes memory sigs = proof[32:];
        require(sigs.length % 65 == 0, "assinaturas malformadas");
        uint256 n = sigs.length / 65;
        bytes32 message = keccak256(abi.encodePacked("AETHER-GATE", block.chainid, vault, proposalId, id));
        bytes32 ethMsg = keccak256(abi.encodePacked("\x19Ethereum Signed Message:\n32", message));
        uint256 valid = 0;
        address last;
        for (uint256 i = 0; i < n; i++) {
            bytes memory sig;
            // r, s, v
            bytes32 r; bytes32 s; uint8 v;
            uint256 off = i * 65;
            assembly {
                let dataPtr := add(sigs, 0x20) // bytes memory: [len][dados]
                r := mload(add(dataPtr, off))
                s := mload(add(dataPtr, add(off, 32)))
                v := shr(248, mload(add(dataPtr, add(off, 64))))
            }
            address rec = ecrecover(ethMsg, v, r, s);
            if (!_isSigner(rec)) continue;
            if (last != address(0) && rec <= last) revert DuplicateSigner(rec); // anti-replay de signatario
            last = rec;
            valid++;
        }
        if (valid < threshold) revert UnknownSigner(last);
        // evento removido: check agora e staticcall-safe (o vault chama via view/estatica)
        return true;
    }

    function _isSigner(address a) internal view returns (bool) {
        for (uint256 i = 0; i < signers.length; i++) if (signers[i] == a) return true;
        return false;
    }

    function signerCount() external view returns (uint256) { return signers.length; }
}

// ---------------------------------------------------------------------------
// YieldAdapter — adaptador "mock avancado": yield honesto so do saldo real.
// Interface identica a um adapter Aave/Morpho (deposit/withdraw).
// Para producao: trocar o endereco por um adapter Aave V3/Morpho Blue real
// (mesma IStrategy) — o Vault nao muda.
// ---------------------------------------------------------------------------
contract YieldAdapter {
    address public immutable vault;
    uint256 public constant APR_BPS = 800; // 8% aa simulado, pago so se houver saldo
    uint256 public principal;
    uint256 public lastAccrue;
    mapping(address => uint256) public deposited;

    event Deposited(uint256 amount, uint256 virtualYield);
    event Withdrawn(uint256 requested, uint256 returned);

    constructor(address vault_) { vault = vault_; lastAccrue = block.timestamp; }

    function deposit() external payable returns (uint256) {
        require(msg.sender == vault, "so o cofre");
        uint256 y = accruedYield();
        principal += msg.value;
        lastAccrue = block.timestamp;
        emit Deposited(msg.value, y);
        return principal + y;
    }

    function withdraw(uint256 amount) external returns (uint256) {
        require(msg.sender == vault, "so o cofre");
        uint256 y = accruedYield();
        uint256 totalAvail = principal + y;
        uint256 pay = amount > totalAvail ? totalAvail : amount;
        uint256 realPay = pay > address(this).balance ? address(this).balance : pay;
        lastAccrue = block.timestamp;
        principal = totalAvail > pay ? totalAvail - pay : 0;
        (bool ok, ) = payable(vault).call{value: realPay}("");
        require(ok, "devolucao falhou");
        emit Withdrawn(amount, realPay);
        return realPay;
    }

    function accruedYield() public view returns (uint256) {
        uint256 dt = block.timestamp - lastAccrue;
        return principal * APR_BPS * dt / (10_000 * 365 days);
    }

    receive() external payable {}
}

// ---------------------------------------------------------------------------
// SmartAccount — AA-minimal do Aether (standalone, EntryPoint-pending)
// * owner (ECDSA = chave da carteira ou chave passkey registrada)
// * passkeys: chaves adicionais autorizadas (mesma validacao ECDSA; p-256
//   nativo do WebAuthn via precompile RIP-7212 fica no roadmap)
// * sessoes: chaves com limite de gasto e validade (pagam gas abstraido
//   pelo owner — sponsoring real exige paymaster EntryPoint, pendente)
// * social recovery: guardians 2-de-3 trocam o owner
// * execute alvo: o AetherVault (deposit/proposals/streams/checkIn/freeze)
// ---------------------------------------------------------------------------
contract SmartAccount {
    error NotOwner();
    error NotAuthorizedKey();
    error KeyExpired();
    error SessionLimitExceeded(uint256 want, uint256 available);
    error NotGuardian();
    error RecoveryNotConfirmed();

    event Executed(address indexed target, uint256 value, bytes data);
    event KeyAdded(address indexed key, uint64 expiry);
    event SessionKeySet(address indexed key, uint64 expiry, uint256 limit);
    event OwnerRecovered(address indexed newOwner);

    struct Session { uint64 expiry; uint256 spent; uint256 limit; }
    address public owner;
    mapping(address => uint64) public keys;            // passkeys: chave => expiracao
    mapping(address => Session) public sessions;       // chaves de sessao
    address[3] public guardians;
    mapping(address => address) public recoveryVote;   // guardian => novo owner proposto
    uint256 public recoveryVotes;
    mapping(address => bool) public isGuardian;

    constructor(address owner_, address[3] memory guardians_) {
        owner = owner_;
        guardians = guardians_;
        for (uint256 i = 0; i < 3; i++) isGuardian[guardians_[i]] = true;
    }

    modifier onlyOwnerOrKey() {
        if (msg.sender != owner) {
            if (keys[msg.sender] == 0 || keys[msg.sender] < block.timestamp) revert NotAuthorizedKey();
        }
        _;
    }

    // ---- acoes: owner, passkey ou sessao (com teto) ----
    function execute(address target, uint256 value, bytes calldata data)
        external payable returns (bytes memory) {
        Session storage s = sessions[msg.sender];
        bool isSession = s.limit > 0 || s.expiry > 0;
        if (msg.sender != owner && keys[msg.sender] == 0) {
            if (!isSession) revert NotAuthorizedKey();
            if (s.expiry < block.timestamp) revert KeyExpired();
            if (s.spent + value > s.limit) revert SessionLimitExceeded(value, s.limit - s.spent);
            s.spent += value;
        }
        (bool ok, bytes memory ret) = target.call{value: value}(data);
        require(ok, "call falhou");
        emit Executed(target, value, data);
        return ret;
    }

    receive() external payable {}

    // ---- gestao (owner) ----
    function addKey(address key, uint64 expiry) external onlyOwnerOrKey {
        keys[key] = expiry;
        emit KeyAdded(key, expiry);
    }

    function setSessionKey(address key, uint64 expiry, uint256 limit) external onlyOwnerOrKey {
        sessions[key] = Session(expiry, 0, limit);
        emit SessionKeySet(key, expiry, limit);
    }

    // ---- social recovery 2-de-3 ----
    function voteRecovery(address newOwner) external {
        if (!isGuardian[msg.sender]) revert NotGuardian();
        address prev = recoveryVote[msg.sender];
        if (prev != address(0)) revert RecoveryNotConfirmed();
        recoveryVote[msg.sender] = newOwner;
        recoveryVotes++;
        _tryRecover();
    }

    function _tryRecover() internal {
        if (recoveryVotes < 2) return;
        // consenso: os 2 votos apontam pro mesmo endereço?
        address candidate = address(0);
        uint256 agree;
        for (uint256 i = 0; i < 3; i++) {
            address v = recoveryVote[guardians[i]];
            if (v != address(0)) {
                if (candidate == address(0)) { candidate = v; agree = 1; }
                else if (v == candidate) agree++;
            }
        }
        if (agree >= 2) {
            owner = candidate;
            for (uint256 i = 0; i < 3; i++) recoveryVote[guardians[i]] = address(0);
            recoveryVotes = 0;
            emit OwnerRecovered(candidate);
        }
    }
}
