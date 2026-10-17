// SPDX-License-Identifier: MIT
// ============================================================================
// AETHER VAULT — Living Shared Vaults (Cofres Vivos Compartilhados)
// Porta Solidity do core Rust/Stylus (ativacao Stylus pausada na Sepolia).
// Mesma logica, mesmos eventos, mesmos erros, contabilidade interna.
// ============================================================================
pragma solidity ^0.8.24;

interface IStrategy {
    function deposit() external payable returns (uint256);
    function withdraw(uint256 amount) external returns (uint256);
}
interface IOracleGate {
    function check(address vault, uint256 proposalId, bytes calldata proof) external returns (bool);
}

contract AetherVault {
    // ---- constantes ----
    uint8 public constant ROLE_MEMBER = 1;
    uint8 public constant ROLE_ADMIN = 2;
    uint64 public constant DAY = 86_400;
    uint64 public constant MIN_FREEZE = 60;
    uint64 public constant MAX_PROPOSAL_LIFE = 30 days;

    // ---- erros tipados ----
    error NotAdmin();
    error NotMember();
    error NotHeir();
    error MemberExists(address who);
    error MemberNotFound(address who);
    error InactiveMember();
    error ThresholdTooHigh(uint256 needed);
    error ProposalNotFound(uint256 id);
    error ProposalExpired();
    error ProposalAlreadyExecuted();
    error AlreadyApproved();
    error InsufficientApprovals(uint256 got, uint256 needed);
    error DailyLimitExceeded(uint256 want, uint256 available);
    error WeeklyLimitExceeded(uint256 want, uint256 available);
    error VaultFrozen(uint64 until);
    error InsufficientBalance(uint256 want, uint256 have);
    error HeirNotArmed();
    error HeirStillWithinGrace(uint64 claimableAt);
    error StreamNotFound(uint256 id);
    error StreamCanceled();
    error StreamNotStarted();
    error StreamZeroDuration();
    error Reentrant();
    error ZeroAddress();
    error NotProposerOrAdmin();
    error StrategyNotSet();
    error NotInitialized();

    // ---- eventos ----
    event Deposit(address indexed from, uint256 amount);
    event WithdrawExecuted(address indexed member, address indexed to, uint256 amount);
    event MemberAdded(address indexed member, uint8 role);
    event MemberRemoved(address indexed member);
    event ThresholdSet(uint256 threshold);
    event ProposalCreated(uint256 indexed id, address to, uint256 amount, address proposer);
    event ProposalApproved(uint256 indexed id, address indexed approver);
    event ProposalExecuted(uint256 indexed id, address indexed to, uint256 amount);
    event ProposalCanceled(uint256 indexed id);
    event StreamCreated(uint256 indexed id, address indexed recipient, uint256 total, uint64 end);
    event StreamClaimed(uint256 indexed id, address indexed recipient, uint256 amount);
    event StreamRevoked(uint256 indexed id, uint256 refunded);
    event CheckIn(address indexed member, uint64 at);
    event HeirArmed(address indexed heir, uint64 graceSeconds);
    event InheritanceTriggered(address indexed oldOwner, address indexed newOwner);
    event EmergencyActivated(uint64 until);
    event EmergencyDeactivated(uint64 at);
    event StrategySet(address adapter);
    event StrategyDeposited(uint256 amount);
    event StrategyWithdrawn(uint256 requested, uint256 received);

    // ---- tipos ----
    struct Member {
        uint8 role;             // 0=nenhum 1=member 2=admin
        bool active;
        uint256 dailyLimit;
        uint256 weeklyLimit;
        uint256 spentToday;
        uint256 spentWeek;
        uint64 dayAnchor;
        uint64 weekAnchor;
    }
    struct Proposal {
        address to;
        uint256 amount;
        uint64 createdAt;
        uint64 deadline;
        bool executed;
        bool requiresOracle;
        address proposer;
        uint8 approvals;
    }
    struct Stream {
        address recipient;
        uint256 total;
        uint256 withdrawn;
        uint64 start;
        uint64 end;
        bool canceled;
    }

    // ---- estado ----
    string public vaultName;
    address public owner;
    bool public initialized;
    bool public frozen;
    uint64 public freezeUntil;
    bool private _lock;
    uint256 public ethBalance;
    uint256 public strategyBalance;
    address[] public memberList;
    mapping(address => Member) public members;
    uint256 public threshold;
    Proposal[] public proposals;
    mapping(uint256 => mapping(address => bool)) public approvedBy;
    Stream[] public streams;
    address public heir;
    uint64 public checkinInterval;
    uint64 public lastCheckin;
    address public strategyAdapter;
    address public oracleGate;

    // ---- modificadores ----
    modifier onlyAdmin() {
        Member memory m = members[msg.sender];
        if (m.role != ROLE_ADMIN || !m.active) revert NotAdmin();
        _;
    }
    modifier noReentrant() {
        if (_lock) revert Reentrant();
        _lock = true;
        _;
        _lock = false;
    }
    modifier initialized_() {
        if (!initialized) revert NotInitialized();
        _;
    }

    // ---- ciclo de vida ----
    function init(string calldata name) external {
        if (initialized) return; // idempotente
        if (msg.sender == address(0)) revert ZeroAddress();
        vaultName = name;
        owner = msg.sender;
        initialized = true;
        threshold = 1;
        lastCheckin = uint64(block.timestamp);
        _addMember(msg.sender, ROLE_ADMIN, type(uint256).max, type(uint256).max);
    }

    /// init via factory: owner explicito (a factory nao ganha privilegios)
    function initFor(address owner_, string calldata name) external {
        if (initialized) return;
        if (owner_ == address(0)) revert ZeroAddress();
        vaultName = name;
        owner = owner_;
        initialized = true;
        threshold = 1;
        lastCheckin = uint64(block.timestamp);
        _addMember(owner_, ROLE_ADMIN, type(uint256).max, type(uint256).max);
    }

    // ---- depositos: qualquer um pode alimentar (cofre publico) ----
    receive() external payable { _credit(msg.sender); }
    function deposit() external payable { _credit(msg.sender); }

    function _credit(address from) internal {
        ethBalance += msg.value;
        emit Deposit(from, msg.value);
    }

    // ---- administracao de membros ----
    function addMember(address who, uint256 dailyLimit, uint256 weeklyLimit)
        external onlyAdmin initialized_ { _addMember(who, ROLE_MEMBER, dailyLimit, weeklyLimit); }

    function promoteMember(address who) external onlyAdmin initialized_ {
        if (members[who].role == 0) revert MemberNotFound(who);
        Member storage m = members[who];
        m.role = ROLE_ADMIN;
        m.dailyLimit = type(uint256).max;
        m.weeklyLimit = type(uint256).max;
        emit MemberAdded(who, ROLE_ADMIN);
    }

    function removeMember(address who) external onlyAdmin initialized_ {
        if (who == owner) revert NotAdmin();
        if (members[who].role == 0) revert MemberNotFound(who);
        Member storage m = members[who];
        m.active = false;
        m.role = 0;
        emit MemberRemoved(who);
    }

    function setThreshold(uint256 mOfN) external onlyAdmin initialized_ {
        uint256 admins = activeAdminCount();
        if (mOfN == 0 || mOfN > admins) revert ThresholdTooHigh(admins);
        threshold = mOfN;
        emit ThresholdSet(mOfN);
    }

    function _addMember(address who, uint8 role, uint256 daily, uint256 weekly) internal {
        if (who == address(0)) revert ZeroAddress();
        if (members[who].role != 0) revert MemberExists(who);
        memberList.push(who);
        Member storage m = members[who];
        m.role = role;
        m.active = true;
        m.dailyLimit = daily;
        m.weeklyLimit = weekly;
        m.spentToday = 0;
        m.spentWeek = 0;
        m.dayAnchor = uint64(block.timestamp);
        m.weekAnchor = uint64(block.timestamp);
        emit MemberAdded(who, role);
    }

    // ---- janela rolante: reseta ao virar dia/semana ----
    function _windowReset(uint256 spent, uint64 anchor, uint64 windowLen)
        internal view returns (uint256, uint64) {
        uint64 now_ = uint64(block.timestamp);
        uint256 steps = (now_ - anchor) / windowLen;
        if (steps > 0) return (0, anchor + uint64(steps) * windowLen);
        return (spent, anchor);
    }

    // ---- gasto sob limite (sem multisig) ----
    function withdrawUnderLimit(address to, uint256 amount)
        external noReentrant initialized_ {
        Member storage m = members[msg.sender];
        if (m.role == 0) revert NotMember();
        if (!m.active) revert InactiveMember();
        if (amount == 0) revert InsufficientBalance(0, 0);
        _guardFrozen();
        if (m.role != ROLE_ADMIN) {
            (uint256 spentToday, uint64 dayAnchor) = _windowReset(m.spentToday, m.dayAnchor, DAY);
            (uint256 spentWeek, uint64 weekAnchor) = _windowReset(m.spentWeek, m.weekAnchor, 7 * DAY);
            uint256 availDay = m.dailyLimit > spentToday ? m.dailyLimit - spentToday : 0;
            uint256 availWeek = m.weeklyLimit > spentWeek ? m.weeklyLimit - spentWeek : 0;
            if (amount > availDay) revert DailyLimitExceeded(amount, availDay);
            if (amount > availWeek) revert WeeklyLimitExceeded(amount, availWeek);
            m.spentToday = spentToday + amount;
            m.spentWeek = spentWeek + amount;
            m.dayAnchor = dayAnchor;
            m.weekAnchor = weekAnchor;
        }
        _sendEth(to, amount);
        emit WithdrawExecuted(msg.sender, to, amount);
    }

    // ---- multisig de grandes saidas ----
    function proposeSpend(address to, uint256 amount, uint64 minutesAlive, bool requiresOracle)
        external initialized_ returns (uint256) {
        Member memory m = members[msg.sender];
        if (m.role == 0) revert NotMember();
        if (!m.active) revert InactiveMember();
        uint64 life = minutesAlive * 60;
        if (life == 0 || life > MAX_PROPOSAL_LIFE) revert ProposalExpired();
        if (to == address(0)) revert ZeroAddress();
        uint256 id = proposals.length;
        proposals.push(Proposal({
            to: to, amount: amount, createdAt: uint64(block.timestamp),
            deadline: uint64(block.timestamp) + life, executed: false,
            requiresOracle: requiresOracle, proposer: msg.sender, approvals: 0
        }));
        emit ProposalCreated(id, to, amount, msg.sender);
        return id;
    }

    function approveProposal(uint256 id) external onlyAdmin initialized_ {
        if (id >= proposals.length) revert ProposalNotFound(id);
        Proposal storage p = proposals[id];
        if (p.executed) revert ProposalAlreadyExecuted();
        if (block.timestamp > p.deadline) revert ProposalExpired();
        if (approvedBy[id][msg.sender]) revert AlreadyApproved();
        approvedBy[id][msg.sender] = true;
        p.approvals += 1;
        emit ProposalApproved(id, msg.sender);
    }

    function executeProposal(uint256 id, bytes calldata oracleProof)
        external noReentrant initialized_ {
        if (id >= proposals.length) revert ProposalNotFound(id);
        Proposal storage p = proposals[id];
        if (p.executed) revert ProposalAlreadyExecuted();
        if (block.timestamp > p.deadline) revert ProposalExpired();
        _guardFrozen();
        if (p.approvals < threshold) revert InsufficientApprovals(p.approvals, threshold);
        if (p.requiresOracle) {
            if (oracleGate == address(0)) revert StrategyNotSet();
            bool ok = IOracleGate(oracleGate).check(address(this), id, oracleProof);
            if (!ok) revert ProposalExpired();
        }
        p.executed = true;
        _sendEth(p.to, p.amount);
        emit ProposalExecuted(id, p.to, p.amount);
    }

    function cancelProposal(uint256 id) external initialized_ {
        if (id >= proposals.length) revert ProposalNotFound(id);
        Proposal storage p = proposals[id];
        bool isAdmin = members[msg.sender].role == ROLE_ADMIN;
        if (p.proposer != msg.sender && !isAdmin) revert NotProposerOrAdmin();
        if (p.executed) revert ProposalAlreadyExecuted();
        p.deadline = 0;
        emit ProposalCanceled(id);
    }

    // ---- streaming de pagamento ----
    function createStream(address recipient, uint256 total, uint64 durationSec)
        external onlyAdmin initialized_ returns (uint256) {
        if (durationSec == 0) revert StreamZeroDuration();
        if (total > ethBalance) revert InsufficientBalance(total, ethBalance);
        uint256 id = streams.length;
        uint64 end = uint64(block.timestamp) + durationSec;
        streams.push(Stream({
            recipient: recipient, total: total, withdrawn: 0,
            start: uint64(block.timestamp), end: end, canceled: false
        }));
        ethBalance -= total; // reserva do stream
        emit StreamCreated(id, recipient, total, end);
        return id;
    }

    function _accrued(Stream storage s) internal view returns (uint256) {
        if (block.timestamp <= s.start || s.end <= s.start) return 0;
        uint256 elapsed = block.timestamp > s.end ? s.end - s.start : block.timestamp - s.start;
        uint256 span = s.end - s.start;
        return (s.total * elapsed / span) - s.withdrawn;
    }

    function withdrawStream(uint256 id) external noReentrant initialized_ returns (uint256) {
        if (id >= streams.length) revert StreamNotFound(id);
        Stream storage s = streams[id];
        if (s.canceled) revert StreamCanceled();
        _guardFrozen();
        uint256 due = _accrued(s);
        if (due == 0) revert StreamNotStarted();
        s.withdrawn += due;
        _sendEth(s.recipient, due);
        emit StreamClaimed(id, s.recipient, due);
        return due;
    }

    function cancelStream(uint256 id) external onlyAdmin initialized_ {
        if (id >= streams.length) revert StreamNotFound(id);
        Stream storage s = streams[id];
        if (s.canceled) revert StreamCanceled();
        uint256 due = _accrued(s);
        uint256 remaining = s.total - s.withdrawn - due;
        s.canceled = true;
        s.end = uint64(block.timestamp);
        if (remaining > 0) ethBalance += remaining;
        emit StreamRevoked(id, remaining);
    }

    // ---- dead man's switch + heranca ----
    function checkIn() external initialized_ {
        Member memory m = members[msg.sender];
        if (m.role == 0) revert NotMember();
        if (!m.active) revert InactiveMember();
        lastCheckin = uint64(block.timestamp);
        emit CheckIn(msg.sender, uint64(block.timestamp));
    }

    function setHeir(address who, uint64 graceSeconds) external initialized_ {
        if (msg.sender != owner) revert NotAdmin();
        heir = who;
        checkinInterval = graceSeconds;
        emit HeirArmed(who, graceSeconds);
    }

    function claimAsHeir() external initialized_ {
        if (msg.sender != heir) revert NotHeir();
        if (checkinInterval == 0 || heir == address(0)) revert HeirNotArmed();
        uint64 claimableAt = lastCheckin + checkinInterval;
        if (block.timestamp < claimableAt) revert HeirStillWithinGrace(claimableAt);
        address old = owner;
        owner = msg.sender;
        // FIX v1.1: herdeiro que ja e membro e PROMOVIDO (antes: MemberExists revertia a heranca)
        if (members[msg.sender].role != 0) {
            Member storage m = members[msg.sender];
            m.role = ROLE_ADMIN;
            m.active = true;
            m.dailyLimit = type(uint256).max;
            m.weeklyLimit = type(uint256).max;
        } else {
            _addMember(msg.sender, ROLE_ADMIN, type(uint256).max, type(uint256).max);
        }
        emit InheritanceTriggered(old, msg.sender);
    }

    // ---- modo emergencia com timelock ----
    function emergencyFreeze(uint64 minutes_) external onlyAdmin initialized_ {
        // FIX v1.2: MIN_FREEZE e em SEGUNDOS (antes comparava contra minutos => congelava 1h)
        uint64 secs = minutes_ * 60 < MIN_FREEZE ? MIN_FREEZE : minutes_ * 60;
        frozen = true;
        freezeUntil = uint64(block.timestamp) + secs;
        emit EmergencyActivated(freezeUntil);
    }

    function unfreeze() external onlyAdmin initialized_ {
        if (frozen && block.timestamp < freezeUntil) revert VaultFrozen(freezeUntil);
        frozen = false;
        freezeUntil = 0;
        emit EmergencyDeactivated(uint64(block.timestamp));
    }

    // ---- yield encaixavel ----
    function setStrategy(address adapter) external onlyAdmin initialized_ {
        strategyAdapter = adapter;
        emit StrategySet(adapter);
    }

    function deployToStrategy(uint256 amount) external onlyAdmin noReentrant initialized_ {
        if (strategyAdapter == address(0)) revert StrategyNotSet();
        if (amount > ethBalance) revert InsufficientBalance(amount, ethBalance);
        ethBalance -= amount;
        IStrategy(strategyAdapter).deposit{value: amount}();
        strategyBalance += amount;
        emit StrategyDeposited(amount);
    }

    function harvestFromStrategy(uint256 amount) external onlyAdmin noReentrant initialized_ {
        if (strategyAdapter == address(0)) revert StrategyNotSet();
        if (amount > strategyBalance) revert InsufficientBalance(amount, strategyBalance);
        uint256 got = IStrategy(strategyAdapter).withdraw(amount);
        strategyBalance -= amount;
        ethBalance += got;
        emit StrategyWithdrawn(amount, got);
    }

    function setOracleGate(address gate) external onlyAdmin initialized_ {
        oracleGate = gate;
    }

    // ---- internos ----
    function _guardFrozen() internal view {
        if (frozen && block.timestamp < freezeUntil) revert VaultFrozen(freezeUntil);
    }

    function activeAdminCount() public view returns (uint256) {
        uint256 count = 0;
        for (uint256 i = 0; i < memberList.length; i++) {
            Member memory m = members[memberList[i]];
            if (m.active && m.role == ROLE_ADMIN) count++;
        }
        return count;
    }

    function _sendEth(address to, uint256 amount) internal {
        if (amount > ethBalance) revert InsufficientBalance(amount, ethBalance);
        ethBalance -= amount;
        if (amount > 0) {
            (bool ok, ) = payable(to).call{value: amount}("");
            if (!ok) revert Reentrant();
        }
    }

    // ---- views ----
    function memberCount() external view returns (uint256) { return memberList.length; }
    function proposalCount() external view returns (uint256) { return proposals.length; }
    function streamCount() external view returns (uint256) { return streams.length; }
    function vaultInfo() external view returns (string memory, uint256, uint256, uint256, bool) {
        return (vaultName, ethBalance, strategyBalance, threshold, frozen);
    }
}

// ============================================================================
// MockStrategy — adaptador de yield para a prova (devolve +10% de "rendimento")
// Interface: IStrategy. Em producao, substituir por adaptador Aave/Morpho real.
// ============================================================================
contract MockStrategy {
    address public immutable vault;
    uint256 public total;

    constructor(address vault_) { vault = vault_; }

    function deposit() external payable returns (uint256) {
        require(msg.sender == vault, "so o cofre");
        total += msg.value;
        return total;
    }

    function withdraw(uint256 amount) external returns (uint256) {
        require(msg.sender == vault, "so o cofre");
        uint256 got = amount + (amount / 10); // simula 10% de yield
        total = total < amount ? 0 : total - amount;
        (bool ok, ) = payable(vault).call{value: got}("");
        require(ok, "devolucao falhou");
        return got;
    }

    receive() external payable {}
}
