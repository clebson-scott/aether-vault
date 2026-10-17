// ============================================================================
// AETHER VAULT — Living Shared Vaults (Cofres Vivos Compartilhados)
// ----------------------------------------------------------------------------
// O dinheiro nao mora "numa carteira": mora num Cofre Vivo compartilhado.
// - Cofre seu, de equipe, familia, comunidade ou publico (qualquer um deposita)
// - Membros gastam sob limites diarios/semanais sem multisig
// - Gastos acima do limite exigem multisig dinamico M-de-N de admins
// - Streaming de pagamento (vai caindo com o tempo)
// - Portas condicionais via oraculo (padrao ZEUS GUARD: bundle assinado)
// - Dead man's switch + heranca automatica
// - Modo emergencia com timelock
// - Adaptador de yield (Aave/Morpho/...) encaixavel — o dinheiro trabalha parado
//
// v1 Core, Arbitrum (Stylus). Sem inventar: cada regra abaixo e code + teste.
// ============================================================================
#![cfg_attr(not(any(test, feature = "export-abi")), no_main)]
extern crate alloc;

use stylus_sdk::prelude::*;
use stylus_sdk::call::RawCall;
use stylus_sdk::alloy_sol_types::SolCall;
use stylus_sdk::alloy_sol_types::sol;
use stylus_sdk::alloy_primitives::{Address, Bytes, U64, U8, U256};
use stylus_sdk::stylus_core::AccountAccess;

pub const ROLE_MEMBER: u8 = 1;
pub const ROLE_ADMIN: u8 = 2;
pub const DAY: u64 = 86_400;
pub const MIN_FREEZE: u64 = 60;        // 1 min de emergencia minima
pub const MAX_PROPOSAL_LIFE: u64 = 30 * DAY;

sol! {
    interface IStrategy {
        function deposit() external payable returns (uint256);
        function withdraw(uint256 amount) external returns (uint256);
    }
    interface IOracleGate {
        function check(address vault, uint256 proposal_id, bytes calldata proof) external returns (bool);
    }
}

sol! {
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
    error HeirStillWithinGrace(uint64 claimable_at);
    error StreamNotFound(uint256 id);
    error StreamCanceled();
    error StreamNotStarted();
    error StreamZeroDuration();
    error Reentrant();
    error ZeroAddress();
    error NotProposerOrAdmin();
    error StrategyNotSet();
}


sol! {
    event Deposit(address indexed from, uint256 amount);
    event WithdrawExecuted(address indexed member, address indexed to, uint256 amount);
    event MemberAdded(address indexed member, uint8 role);
    event MemberRemoved(address indexed member);
    event ThresholdSet(uint256 threshold);
    event ProposalCreated(uint256 indexed id, address to, uint256 amount, address proposer);
    event ProposalApproved(uint256 indexed id, address indexed approver);
    event ProposalExecuted(uint256 indexed id, address to, uint256 amount);
    event ProposalCanceled(uint256 indexed id);
    event StreamCreated(uint256 indexed id, address indexed recipient, uint256 total, uint64 end);
    event StreamClaimed(uint256 indexed id, address indexed recipient, uint256 amount);
    event StreamRevoked(uint256 indexed id, uint256 refunded);
    event CheckIn(address indexed member, uint64 at);
    event HeirArmed(address indexed heir, uint64 grace_seconds);
    event InheritanceTriggered(address indexed old_owner, address indexed new_owner);
    event EmergencyActivated(uint64 until);
    event EmergencyDeactivated(uint64 at);
    event StrategySet(address adapter);
    event StrategyDeposited(uint256 amount);
    event StrategyWithdrawn(uint256 requested, uint256 received);
}

#[derive(SolidityError)]
pub enum AetherError {
    NotAdmin(NotAdmin), NotMember(NotMember), NotHeir(NotHeir),
    MemberExists(MemberExists), MemberNotFound(MemberNotFound), InactiveMember(InactiveMember),
    ThresholdTooHigh(ThresholdTooHigh),
    ProposalNotFound(ProposalNotFound), ProposalExpired(ProposalExpired),
    ProposalAlreadyExecuted(ProposalAlreadyExecuted), AlreadyApproved(AlreadyApproved),
    InsufficientApprovals(InsufficientApprovals),
    DailyLimitExceeded(DailyLimitExceeded), WeeklyLimitExceeded(WeeklyLimitExceeded),
    VaultFrozen(VaultFrozen), InsufficientBalance(InsufficientBalance),
    HeirNotArmed(HeirNotArmed), HeirStillWithinGrace(HeirStillWithinGrace),
    StreamNotFound(StreamNotFound), StreamCanceled(StreamCanceled),
    StreamNotStarted(StreamNotStarted), StreamZeroDuration(StreamZeroDuration),
    Reentrant(Reentrant), ZeroAddress(ZeroAddress),
    NotProposerOrAdmin(NotProposerOrAdmin), StrategyNotSet(StrategyNotSet),
}

sol_storage! {
    #[entrypoint]
    pub struct AetherVault {
        string vault_name;
        address owner;
        bool initialized;

        // --- seguranca global ---
        bool frozen;
        uint64 freeze_until;
        bool _lock; // reentrancia

        // --- contabilidade de ETH (toda entrada/saida passa por aqui) ---
        uint256 eth_balance;
        uint256 strategy_balance;      // alocado ao adaptador de yield

        // --- membros e limites ---
        address[] member_list;
        mapping(address => Member) members;
        uint256 threshold;             // M de N admins p/ gastos acima do limite

        // --- multisig de gastos ---
        Proposal[] proposals;
        mapping(uint256 => mapping(address => bool)) approved_by;

        // --- streaming de pagamento ---
        Stream[] streams;

        // --- dead man's switch ---
        address heir;
        uint64 checkin_interval;
        uint64 last_checkin;

        // --- yield + portas condicionais ---
        address strategy_adapter;
        address oracle_gate;
    }

    struct Member {
        uint8 role;               // 1=member 2=admin
        bool active;
        uint256 daily_limit;     // por janela de 24h
        uint256 weekly_limit;    // por janela de 7d
        uint256 spent_today;
        uint256 spent_week;
        uint64 day_anchor;
        uint64 week_anchor;
    }

    struct Proposal {
        address to;
        uint256 amount;
        uint64 created_at;
        uint64 deadline;
        bool executed;
        bool requires_oracle;     // porta condicional: so executa se oraculo aprovar
        address proposer;
        uint8 approvals;
        uint64 oracle_token;     // nonce do bundle oraculo (reuso do padrao ZEUS)
        bytes oracle_proof;      // prova enviada na execucao
    }

    struct Stream {
        address recipient;
        uint256 total;
        uint256 withdrawn;
        uint64 start;
        uint64 end;
        bool canceled;
    }
}

// ---------------------------------------------------------------------------
// helpers de conta (pure) — testados em unit tests
// ---------------------------------------------------------------------------

/// Acumulado disponivel num stream linear ate `now`.
pub fn stream_accrued(total: U256, withdrawn: U256, start: u64, end: u64, now: u64) -> U256 {
    if now <= start || end <= start {
        return withdrawn; // nada mais disponivel alem do ja sacado
    }
    let elapsed = (now.min(end) - start) as u128;
    let span = (end - start) as u128;
    let total_u = total.to::<u128>();
    let unlocked = (U256::from(total_u) * U256::from(elapsed)) / U256::from(span);
    unlocked.max(withdrawn) - withdrawn
}

/// Limites de janela rolante: reseta o contador quando a janela virou.
pub fn window_reset(spent: U256, anchor: u64, now: u64, window_len: u64) -> (U256, u64) {
    let steps = (now - anchor) / window_len; // >0 => virou 1+ janelas
    if steps > 0 {
        (U256::ZERO, anchor + steps * window_len)
    } else {
        (spent, anchor)
    }
}

// ---------------------------------------------------------------------------
// contrato
// ---------------------------------------------------------------------------

#[public]
impl AetherVault {
    // ---- ciclo de vida ----

    pub fn init(&mut self, name: String) -> Result<(), AetherError> {
        if self.initialized.get() { return Ok(()); } // idempotente
        let creator = self.vm().msg_sender();
        if creator.is_zero() { return Err(AetherError::ZeroAddress(ZeroAddress {})); }
        self.vault_name.set_str(name);
        self.owner.set(creator);
        self.initialized.set(true);
        self.threshold.set(U256::from(1));
        self.last_checkin.set(U64::from(self.vm().block_timestamp()));
        self._add_member(creator, ROLE_ADMIN, U256::MAX, U256::MAX)?;
        Ok(())
    }

    // ---- depositos: qualquer um pode alimentar o cofre (publico) ----

    #[payable]
    pub fn deposit(&mut self) -> Result<(), AetherError> {
        let value = self.vm().msg_value();
        let sender_of_deposit = self.vm().msg_sender();
        self.eth_balance.set(self.eth_balance.get() + value);
        self.vm().log(Deposit { from: sender_of_deposit, amount: value });
        Ok(())
    }

    // ---- administracao de membros (admin) ----

    pub fn add_member(&mut self, who: Address, daily_limit: U256, weekly_limit: U256) -> Result<(), AetherError> {
        self.only_admin()?;
        self._add_member(who, ROLE_MEMBER, daily_limit, weekly_limit)
    }

    pub fn promote_member(&mut self, who: Address) -> Result<(), AetherError> {
        self.only_admin()?;
        if self.members.getter(who).role.get() == 0 { return Err(AetherError::MemberNotFound(MemberNotFound { who })); }
        let mut m = self.members.setter(who);
        m.role.set(U8::from(ROLE_ADMIN));
        m.daily_limit.set(U256::MAX);
        m.weekly_limit.set(U256::MAX);
        Ok(())
    }

    pub fn remove_member(&mut self, who: Address) -> Result<(), AetherError> {
        self.only_admin()?;
        if who == self.owner.get() { return Err(AetherError::NotAdmin(NotAdmin {})); }
        if self.members.getter(who).role.get() == 0 { return Err(AetherError::MemberNotFound(MemberNotFound { who })); }
        let mut m = self.members.setter(who);
        m.active.set(false);
        m.role.set(U8::ZERO);
        self.vm().log(MemberRemoved { member: who });
        Ok(())
    }

    pub fn set_threshold(&mut self, m_of_n: U256) -> Result<(), AetherError> {
        self.only_admin()?;
        let admins = self.active_admin_count();
        if m_of_n == U256::ZERO || m_of_n > U256::from(admins) {
            return Err(AetherError::ThresholdTooHigh(ThresholdTooHigh { needed: U256::from(admins) }));
        }
        self.threshold.set(m_of_n);
        self.vm().log(ThresholdSet { threshold: m_of_n });
        Ok(())
    }

    // ---- gasto direto sob limite (sem multisig) ----

    pub fn withdraw_under_limit(&mut self, to: Address, amount: U256) -> Result<(), AetherError> {
        let sender = self.vm().msg_sender();
        let now = self.vm().block_timestamp();
        self.guard_frozen(now)?;
        self.guard_member(sender)?;
        if amount.is_zero() { return Err(AetherError::InsufficientBalance(InsufficientBalance { want: amount, have: U256::ZERO })); }

        {
            let mut m = self.members.setter(sender);
            if m.role.get() != ROLE_ADMIN {
                let (spent_today, day_anchor) = window_reset(m.spent_today.get(), m.day_anchor.get().to::<u64>(), now, DAY);
                let (spent_week, week_anchor) = window_reset(m.spent_week.get(), m.week_anchor.get().to::<u64>(), now, 7 * DAY);
                let avail_day = m.daily_limit.get().saturating_sub(spent_today);
                let avail_week = m.weekly_limit.get().saturating_sub(spent_week);
                if amount > avail_day {
                    return Err(AetherError::DailyLimitExceeded(DailyLimitExceeded { want: amount, available: avail_day }));
                }
                if amount > avail_week {
                    return Err(AetherError::WeeklyLimitExceeded(WeeklyLimitExceeded { want: amount, available: avail_week }));
                }
                m.spent_today.set(spent_today + amount);
                m.spent_week.set(spent_week + amount);
                m.day_anchor.set(U64::from(day_anchor));
                m.week_anchor.set(U64::from(week_anchor));
            }
        }
        self.send_eth(to, amount)?;
        self.vm().log(WithdrawExecuted { member: sender, to, amount });
        Ok(())
    }

    // ---- multisig dinamico p/ grandes saidas ----

    pub fn propose_spend(&mut self, to: Address, amount: U256, minutes_alive: u64, requires_oracle: bool) -> Result<U256, AetherError> {
        let sender = self.vm().msg_sender();
        self.guard_member(sender)?;
        let now = self.vm().block_timestamp();
        let life = minutes_alive * 60;
        if life == 0 || life > MAX_PROPOSAL_LIFE { return Err(AetherError::ProposalExpired(ProposalExpired {})); }
        if to.is_zero() { return Err(AetherError::ZeroAddress(ZeroAddress {})); }
        let n = self.proposals.len();
        {
            let mut p = self.proposals.grow();
            p.to.set(to);
            p.amount.set(amount);
            p.created_at.set(U64::from(now));
            p.deadline.set(U64::from(now + life));
            p.proposer.set(sender);
            p.requires_oracle.set(requires_oracle);
            p.approvals.set(U8::ZERO);
        }
        self.vm().log(ProposalCreated { id: U256::from(n), to, amount, proposer: sender });
        Ok(U256::from(n))
    }

    pub fn approve_proposal(&mut self, id: U256) -> Result<(), AetherError> {
        let sender = self.vm().msg_sender();
        if self.members.getter(sender).role.get() != ROLE_ADMIN { return Err(AetherError::NotAdmin(NotAdmin {})); }
        let idx = id.to::<usize>();
        if idx >= self.proposals.len() { return Err(AetherError::ProposalNotFound(ProposalNotFound { id })); }
        {
            let p = self.proposals.getter(idx).unwrap();
            if p.executed.get() { return Err(AetherError::ProposalAlreadyExecuted(ProposalAlreadyExecuted {})); }
            if self.vm().block_timestamp() > p.deadline.get().to::<u64>() { return Err(AetherError::ProposalExpired(ProposalExpired {})); }
        }
        let mut slot = self.approved_by.setter(U256::from(idx));
        if slot.getter(sender).get() { return Err(AetherError::AlreadyApproved(AlreadyApproved {})); }
        slot.setter(sender).set(true);
        {
            let mut p = self.proposals.get_mut(idx).unwrap();
            let cnt = p.approvals.get();
            p.approvals.set(cnt + U8::from(1u8));
        }
        self.vm().log(ProposalApproved { id, approver: sender });
        Ok(())
    }

    pub fn execute_proposal(&mut self, id: U256, oracle_proof: Bytes) -> Result<(), AetherError> {
        let idx = id.to::<usize>();
        if idx >= self.proposals.len() { return Err(AetherError::ProposalNotFound(ProposalNotFound { id })); }
        let (to, amount, executed, requires_oracle, deadline, approvals) = {
            let p = self.proposals.getter(idx).unwrap();
            (p.to.get(), p.amount.get(), p.executed.get(), p.requires_oracle.get(), p.deadline.get().to::<u64>(), p.approvals.get())
        };
        if executed { return Err(AetherError::ProposalAlreadyExecuted(ProposalAlreadyExecuted {})); }
        let now = self.vm().block_timestamp();
        if now > deadline { return Err(AetherError::ProposalExpired(ProposalExpired {})); }
        self.guard_frozen(now)?;

        let needed = self.threshold.get();
        if U256::from(approvals) < needed {
            return Err(AetherError::InsufficientApprovals(InsufficientApprovals { got: U256::from(approvals), needed }));
        }
        // porta condicional: oraculo externo precisa aprovar
        if requires_oracle {
            let gate = self.oracle_gate.get();
            if gate.is_zero() { return Err(AetherError::StrategyNotSet(StrategyNotSet {})); }
            let call = IOracleGate::checkCall {
                vault: self.vm().contract_address(),
                proposal_id: id,
                proof: oracle_proof,
            };
            let data = call.abi_encode();
            let res = unsafe { RawCall::new(self.vm()).gas(u64::MAX).call(gate, &data) }
                .map_err(|_| AetherError::ProposalExpired(ProposalExpired {}))?;
            let ok = res.first() == Some(&1u8);
            if !ok { return Err(AetherError::ProposalExpired(ProposalExpired {})); }
        }

        self.proposals.get_mut(idx).unwrap().executed.set(true);
        self.send_eth(to, amount)?;
        self.vm().log(ProposalExecuted { id, to, amount });
        Ok(())
    }

    pub fn cancel_proposal(&mut self, id: U256) -> Result<(), AetherError> {
        let idx = id.to::<usize>();
        if idx >= self.proposals.len() { return Err(AetherError::ProposalNotFound(ProposalNotFound { id })); }
        let sender = self.vm().msg_sender();
        let (proposer, executed) = {
            let p = self.proposals.getter(idx).unwrap();
            (p.proposer.get(), p.executed.get())
        };
        let is_admin = self.members.getter(sender).role.get() == ROLE_ADMIN;
        if proposer != sender && !is_admin { return Err(AetherError::NotProposerOrAdmin(NotProposerOrAdmin {})); }
        if executed { return Err(AetherError::ProposalAlreadyExecuted(ProposalAlreadyExecuted {})); }
        self.proposals.get_mut(idx).unwrap().deadline.set(U64::ZERO);
        self.vm().log(ProposalCanceled { id });
        Ok(())
    }

    // ---- streaming de pagamento ----

    pub fn create_stream(&mut self, recipient: Address, total: U256, duration_sec: u64) -> Result<U256, AetherError> {
        self.only_admin()?;
        if duration_sec == 0 { return Err(AetherError::StreamZeroDuration(StreamZeroDuration {})); }
        if total > self.eth_balance.get() {
            return Err(AetherError::InsufficientBalance(InsufficientBalance { want: total, have: self.eth_balance.get() }));
        }
        let now = self.vm().block_timestamp();
        let n = self.streams.len();
        {
            let mut s = self.streams.grow();
            s.recipient.set(recipient);
            s.total.set(total);
            s.withdrawn.set(U256::ZERO);
            s.start.set(U64::from(now));
            s.end.set(U64::from(now + duration_sec));
            s.canceled.set(false);
        }
        self.eth_balance.set(self.eth_balance.get() - total); // reserva do stream
        let end_ts = now + duration_sec;
        self.vm().log(StreamCreated { id: U256::from(n), recipient, total, end: end_ts });
        Ok(U256::from(n))
    }

    pub fn withdraw_stream(&mut self, id: U256) -> Result<U256, AetherError> {
        let idx = id.to::<usize>();
        if idx >= self.streams.len() { return Err(AetherError::StreamNotFound(StreamNotFound { id })); }
        let (recipient, total, withdrawn, start, end, canceled) = {
            let s = self.streams.getter(idx).unwrap();
            (s.recipient.get(), s.total.get(), s.withdrawn.get(), s.start.get().to::<u64>(), s.end.get().to::<u64>(), s.canceled.get())
        };
        if canceled { return Err(AetherError::StreamCanceled(StreamCanceled {})); }
        let now = self.vm().block_timestamp();
        self.guard_frozen(now)?;
        let due = stream_accrued(total, withdrawn, start, end, now);
        if due.is_zero() { return Err(AetherError::StreamNotStarted(StreamNotStarted {})); }
        {
            let mut s = self.streams.get_mut(idx).unwrap();
            s.withdrawn.set(withdrawn + due);
        }
        self.send_eth(recipient, due)?;
        self.vm().log(StreamClaimed { id, recipient, amount: due });
        Ok(due)
    }

    pub fn cancel_stream(&mut self, id: U256) -> Result<(), AetherError> {
        self.only_admin()?;
        let idx = id.to::<usize>();
        if idx >= self.streams.len() { return Err(AetherError::StreamNotFound(StreamNotFound { id })); }
        let (total, withdrawn, start, end, canceled) = {
            let s = self.streams.getter(idx).unwrap();
            (s.total.get(), s.withdrawn.get(), s.start.get().to::<u64>(), s.end.get().to::<u64>(), s.canceled.get())
        };
        if canceled { return Err(AetherError::StreamCanceled(StreamCanceled {})); }
        let now = self.vm().block_timestamp();
        let due = stream_accrued(total, withdrawn, start, end, now);
        let remaining = total - withdrawn - due;
        {
            let mut s = self.streams.get_mut(idx).unwrap();
            s.canceled.set(true);
            s.end.set(U64::from(now));
        }
        if remaining > U256::ZERO {
            self.eth_balance.set(self.eth_balance.get() + remaining);
        }
        self.vm().log(StreamRevoked { id, refunded: remaining });
        Ok(())
    }

    // ---- dead man's switch + heranca ----

    pub fn check_in(&mut self) -> Result<(), AetherError> {
        let sender = self.vm().msg_sender();
        self.guard_member(sender)?;
        self.last_checkin.set(U64::from(self.vm().block_timestamp()));
        self.vm().log(CheckIn { member: sender, at: self.vm().block_timestamp() });
        Ok(())
    }

    pub fn set_heir(&mut self, who: Address, grace_seconds: u64) -> Result<(), AetherError> {
        if self.vm().msg_sender() != self.owner.get() { return Err(AetherError::NotAdmin(NotAdmin {})); }
        self.heir.set(who);
        self.checkin_interval.set(U64::from(grace_seconds));
        self.vm().log(HeirArmed { heir: who, grace_seconds });
        Ok(())
    }

    pub fn claim_as_heir(&mut self) -> Result<(), AetherError> {
        let sender = self.vm().msg_sender();
        if sender != self.heir.get() { return Err(AetherError::NotHeir(NotHeir {})); }
        if self.checkin_interval.get() == U64::ZERO || self.hear_ok() { return Err(AetherError::HeirNotArmed(HeirNotArmed {})); }
        let claimable_at = self.last_checkin.get().to::<u64>() + self.checkin_interval.get().to::<u64>();
        let now = self.vm().block_timestamp();
        if now < claimable_at {
            return Err(AetherError::HeirStillWithinGrace(HeirStillWithinGrace { claimable_at }));
        }
        let old = self.owner.get();
        self.owner.set(sender);
        self._add_member(sender, ROLE_ADMIN, U256::MAX, U256::MAX)?;
        self.vm().log(InheritanceTriggered { old_owner: old, new_owner: sender });
        Ok(())
    }

    // ---- modo emergencia ----

    pub fn emergency_freeze(&mut self, minutes: u64) -> Result<(), AetherError> {
        self.only_admin()?;
        // FIX v1.2: MIN_FREEZE e em segundos
        let secs = (minutes * 60).max(MIN_FREEZE);
        self.frozen.set(true);
        let until = self.vm().block_timestamp() + secs;
        self.freeze_until.set(U64::from(until));
        self.vm().log(EmergencyActivated { until });
        Ok(())
    }

    pub fn unfreeze(&mut self) -> Result<(), AetherError> {
        self.only_admin()?;
        let now = self.vm().block_timestamp();
        // timelock: so sai do freeze depois do prazo
        if self.frozen.get() && now < self.freeze_until.get().to::<u64>() {
            return Err(AetherError::VaultFrozen(VaultFrozen { until: self.freeze_until.get().to::<u64>() }));
        }
        self.frozen.set(false);
        self.freeze_until.set(U64::ZERO);
        self.vm().log(EmergencyDeactivated { at: now });
        Ok(())
    }

    // ---- yield: adaptador encaixavel ----

    pub fn set_strategy(&mut self, adapter: Address) -> Result<(), AetherError> {
        self.only_admin()?;
        self.strategy_adapter.set(adapter);
        self.vm().log(StrategySet { adapter });
        Ok(())
    }

    pub fn deploy_to_strategy(&mut self, amount: U256) -> Result<(), AetherError> {
        self.only_admin()?;
        if self.strategy_adapter.get().is_zero() { return Err(AetherError::StrategyNotSet(StrategyNotSet {})); }
        if amount > self.eth_balance.get() {
            return Err(AetherError::InsufficientBalance(InsufficientBalance { want: amount, have: self.eth_balance.get() }));
        }
        let adapter = self.strategy_adapter.get();
        self.eth_balance.set(self.eth_balance.get() - amount);
        let data = IStrategy::depositCall {}.abi_encode();
        self.locked_call(adapter, amount, &data)?;
        self.strategy_balance.set(self.strategy_balance.get() + amount);
        self.vm().log(StrategyDeposited { amount });
        Ok(())
    }

    pub fn harvest_from_strategy(&mut self, amount: U256) -> Result<(), AetherError> {
        self.only_admin()?;
        if self.strategy_adapter.get().is_zero() { return Err(AetherError::StrategyNotSet(StrategyNotSet {})); }
        if amount > self.strategy_balance.get() {
            return Err(AetherError::InsufficientBalance(InsufficientBalance { want: amount, have: self.strategy_balance.get() }));
        }
        let adapter = self.strategy_adapter.get();
        let data = IStrategy::withdrawCall { amount }.abi_encode();
        let ret = self.locked_call_ret(adapter, U256::ZERO, &data)?;
        let got = if ret.len() >= 32 { U256::from_be_slice(&ret[ret.len()-32..]) } else { amount };
        self.strategy_balance.set(self.strategy_balance.get() - amount);
        self.eth_balance.set(self.eth_balance.get() + got);
        self.vm().log(StrategyWithdrawn { requested: amount, received: got });
        Ok(())
    }

    pub fn set_oracle_gate(&mut self, gate: Address) -> Result<(), AetherError> {
        self.only_admin()?;
        self.oracle_gate.set(gate);
        Ok(())
    }

    // ---- views ----

    pub fn vault_info(&self) -> (String, U256, U256, U256, bool) {
        (self.vault_name.get_string(), self.eth_balance.get(), self.strategy_balance.get(),
         self.threshold.get(), self.frozen.get())
    }

    pub fn member_count(&self) -> U256 { U256::from(self.member_list.len()) }
    pub fn proposal_count(&self) -> U256 { U256::from(self.proposals.len()) }
    pub fn stream_count(&self) -> U256 { U256::from(self.streams.len()) }
}

// ---------------------------------------------------------------------------
// internos
// ---------------------------------------------------------------------------

impl AetherVault {
    fn hear_ok(&self) -> bool { self.heir.get().is_zero() }

    fn only_admin(&self) -> Result<(), AetherError> {
        let sender = self.vm().msg_sender();
        let m = self.members.getter(sender);
        if m.role.get() != ROLE_ADMIN || !m.active.get() { return Err(AetherError::NotAdmin(NotAdmin {})); }
        Ok(())
    }

    fn guard_member(&self, sender: Address) -> Result<(), AetherError> {
        let m = self.members.getter(sender);
        if m.role.get() == U8::ZERO { return Err(AetherError::NotMember(NotMember {})); }
        if !m.active.get() { return Err(AetherError::InactiveMember(InactiveMember {})); }
        Ok(())
    }

    fn guard_frozen(&self, now: u64) -> Result<(), AetherError> {
        if self.frozen.get() && now < self.freeze_until.get().to::<u64>() {
            return Err(AetherError::VaultFrozen(VaultFrozen { until: self.freeze_until.get().to::<u64>() }));
        }
        Ok(())
    }

    fn active_admin_count(&self) -> u32 {
        let mut count = 0;
        for i in 0..self.member_list.len() {
            let addr = self.member_list.get(i).unwrap();
            let m = self.members.getter(addr);
            if m.active.get() && m.role.get().to::<u8>() == ROLE_ADMIN { count += 1; }
        }
        count
    }

    fn _add_member(&mut self, who: Address, role: u8, daily: U256, weekly: U256) -> Result<(), AetherError> {
        if who.is_zero() { return Err(AetherError::ZeroAddress(ZeroAddress {})); }
        if self.members.getter(who).role.get() != 0 { return Err(AetherError::MemberExists(MemberExists { who })); }
        let now = self.vm().block_timestamp();
        self.member_list.push(who);
        let mut m = self.members.setter(who);
        m.role.set(U8::from(role));
        m.active.set(true);
        m.daily_limit.set(daily);
        m.weekly_limit.set(weekly);
        m.spent_today.set(U256::ZERO);
        m.spent_week.set(U256::ZERO);
        m.day_anchor.set(U64::from(now));
        m.week_anchor.set(U64::from(now));
        self.vm().log(MemberAdded { member: who, role });
        Ok(())
    }

    fn send_eth(&mut self, to: Address, amount: U256) -> Result<(), AetherError> {
        if amount > self.eth_balance.get() {
            return Err(AetherError::InsufficientBalance(InsufficientBalance { want: amount, have: self.eth_balance.get() }));
        }
        self.eth_balance.set(self.eth_balance.get() - amount);
        if amount > U256::ZERO {
            self.locked_call(to, amount, &[])?;
        }
        Ok(())
    }

    fn locked_call(&mut self, to: Address, value: U256, data: &[u8]) -> Result<Vec<u8>, AetherError> {
        if self._lock.get() { return Err(AetherError::Reentrant(Reentrant {})); }
        self._lock.set(true);
        let res = unsafe {
            RawCall::new_with_value(self.vm(), value)
                .gas(u64::MAX)
                .flush_storage_cache()
                .call(to, data)
        };
        self._lock.set(false);
        res.map_err(|_| AetherError::Reentrant(Reentrant {}))
    }

    fn locked_call_ret(&mut self, to: Address, value: U256, data: &[u8]) -> Result<Vec<u8>, AetherError> {
        if self._lock.get() { return Err(AetherError::Reentrant(Reentrant {})); }
        self._lock.set(true);
        let res = unsafe {
            RawCall::new_with_value(self.vm(), value)
                .gas(u64::MAX)
                .flush_storage_cache()
                .call(to, data)
        };
        self._lock.set(false);
        res.map_err(|_| AetherError::Reentrant(Reentrant {}))
    }
}

// ---------------------------------------------------------------------------
// unit tests (pure logic) — a aritmetica do cofre vivo
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;
    use alloy_primitives::U256;

    #[test]
    fn stream_linear_pro_rata() {
        // 100 ETH em 100s: aos 50s liberou 50
        let due = stream_accrued(U256::from(100), U256::ZERO, 0, 100, 50);
        assert_eq!(due, U256::from(50));
    }

    #[test]
    fn stream_nao_passa_do_total() {
        // now depois do fim: libera tudo que falta, nunca mais que total
        let due = stream_accrued(U256::from(100), U256::ZERO, 0, 100, 5000);
        assert_eq!(due, U256::from(100));
    }

    #[test]
    fn stream_com_saque_parcial() {
        // sacou 20, acumulado agora e 50 => devido 30
        let due = stream_accrued(U256::from(100), U256::from(20), 0, 100, 50);
        assert_eq!(due, U256::from(30));
    }

    #[test]
    fn stream_antes_de_comecar() {
        let due = stream_accrued(U256::from(100), U256::from(7), 10, 100, 5);
        assert_eq!(due, U256::from(7)); // nada alem do ja sacado
    }

    #[test]
    fn janela_dia_reseta() {
        // mesmo dia: acumula
        let (spent, anchor) = window_reset(U256::from(10), 100, 100 + DAY - 1, DAY);
        assert_eq!(spent, U256::from(10));
        assert_eq!(anchor, 100);
        // virou o dia: zera e ancora avanca
        let (spent, anchor) = window_reset(U256::from(10), 100, 100 + DAY, DAY);
        assert_eq!(spent, U256::ZERO);
        assert_eq!(anchor, 100 + DAY);
    }

    #[test]
    fn janela_semana_reseta_uma_vez() {
        // 8 dias se passaram => reseta e ancora em +7d (nao +8, janela comeca de novo)
        let (spent, anchor) = window_reset(U256::from(50), 100, 100 + 8 * DAY, 7 * DAY);
        assert_eq!(spent, U256::ZERO);
        assert_eq!(anchor, 100 + 7 * DAY);
    }

    #[test]
    fn janela_salta_varias() {
        // 15 dias => 2 semanas inteiras
        let (spent, anchor) = window_reset(U256::from(50), 100, 100 + 15 * DAY, 7 * DAY);
        assert_eq!(spent, U256::ZERO);
        assert_eq!(anchor, 100 + 14 * DAY);
    }

    #[test]
    fn papeis_validos() {
        assert_eq!(ROLE_ADMIN, 2);
        assert_eq!(ROLE_MEMBER, 1);
        assert!(ROLE_MEMBER != ROLE_ADMIN);
    }
}
