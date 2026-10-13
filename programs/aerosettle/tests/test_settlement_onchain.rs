//! AeroSettle EPIC 2.8.4: real SPL Token settlement integration tests.
//!
//! Runs the entire on-chain lifecycle in LiteSVM and checks that transfers
//! are atomic, destinations are bound, and the vault is emptied exactly.
//! Run after `anchor build --arch v0`.

use aerosettle::{
    AgentType, Capability, CreateWorkOrderArgs, EvidenceRequirement, PaymentModel, SettlementTerms,
    SubmitExecutionArgs, VerificationAttestation, VerificationStatus, VerifyExecutionArgs,
    WorkOrderAccount, WorkOrderStatus, WorkType, AGENT_SEED, ESCROW_VAULT_SEED,
    PROTOCOL_CONFIG_SEED, WORK_ORDER_SEED,
};
use anchor_lang::{
    prelude::Pubkey,
    solana_program::{instruction::Instruction, system_program},
    AccountDeserialize, InstructionData, ToAccountMetas,
};
use anchor_spl::token::{
    spl_token::{
        instruction as spl_instruction,
        state::{Account as SplTokenAccount, AccountState, Mint as SplMint},
    },
    ID as TOKEN_PROGRAM_ID,
};
use litesvm::LiteSVM;
use solana_account::Account;
use solana_clock::Clock;
use solana_keypair::Keypair;
use solana_message::{Message, VersionedMessage};
use solana_program_option::COption;
use solana_program_pack::Pack;
use solana_signer::Signer;
use solana_transaction::versioned::VersionedTransaction;

const TOTAL: u64 = 100_000_000; // 100 tokens with 6 decimals
const BONUS: u64 = 5_000_000;
const DECIMALS: u8 = 6;
const BASE_TIME: i64 = 1_700_000_000;

struct Rig {
    svm: LiteSVM,
    owner: Keypair,
    protocol_config: Pubkey,
    work_order: Pubkey,
    mint: Pubkey,
    vault: Pubkey,
    operator_tokens: Pubkey,
    refund_tokens: Pubkey,
}

fn instruction<D: InstructionData, A: ToAccountMetas>(data: D, accounts: A) -> Instruction {
    Instruction::new_with_bytes(
        aerosettle::id(),
        &data.data(),
        accounts.to_account_metas(None),
    )
}

fn send(svm: &mut LiteSVM, payer: &Keypair, ix: Instruction) -> Result<(), String> {
    let message =
        Message::new_with_blockhash(&[ix], Some(&payer.pubkey()), &svm.latest_blockhash());
    let tx = VersionedTransaction::try_new(VersionedMessage::Legacy(message), &[payer])
        .map_err(|e| format!("sign: {e:?}"))?;
    svm.send_transaction(tx)
        .map(|_| ())
        .map_err(|e| format!("transaction: {e:?}"))
}

fn must_send(svm: &mut LiteSVM, payer: &Keypair, ix: Instruction) {
    let result = send(svm, payer, ix);
    assert!(result.is_ok(), "transaction failed: {result:?}");
}

fn fund_lamports(svm: &mut LiteSVM, keypair: &Keypair) {
    svm.airdrop(&keypair.pubkey(), 5_000_000_000)
        .expect("SOL airdrop");
}

fn set_time(svm: &mut LiteSVM, timestamp: i64) {
    let mut clock = svm.get_sysvar::<Clock>();
    clock.unix_timestamp = timestamp;
    svm.set_sysvar(&clock);
}

fn pda(seeds: &[&[u8]]) -> Pubkey {
    Pubkey::find_program_address(seeds, &aerosettle::id()).0
}

fn make_mint(svm: &mut LiteSVM, authority: Pubkey, supply: u64) -> Pubkey {
    let address = Pubkey::new_unique();
    let state = SplMint {
        mint_authority: COption::Some(authority),
        supply,
        decimals: DECIMALS,
        is_initialized: true,
        freeze_authority: COption::None,
    };
    let mut data = vec![0u8; SplMint::LEN];
    SplMint::pack(state, &mut data).unwrap();
    svm.set_account(
        address,
        Account {
            lamports: svm.minimum_balance_for_rent_exemption(SplMint::LEN),
            data,
            owner: TOKEN_PROGRAM_ID,
            executable: false,
            rent_epoch: 0,
        },
    )
    .unwrap();
    address
}

fn make_token_account(svm: &mut LiteSVM, mint: Pubkey, authority: Pubkey, amount: u64) -> Pubkey {
    let address = Pubkey::new_unique();
    let state = SplTokenAccount {
        mint,
        owner: authority,
        amount,
        delegate: COption::None,
        state: AccountState::Initialized,
        is_native: COption::None,
        delegated_amount: 0,
        close_authority: COption::None,
    };
    let mut data = vec![0u8; SplTokenAccount::LEN];
    SplTokenAccount::pack(state, &mut data).unwrap();
    svm.set_account(
        address,
        Account {
            lamports: svm.minimum_balance_for_rent_exemption(SplTokenAccount::LEN),
            data,
            owner: TOKEN_PROGRAM_ID,
            executable: false,
            rent_epoch: 0,
        },
    )
    .unwrap();
    address
}

fn token_balance(svm: &LiteSVM, address: Pubkey) -> u64 {
    let account = svm.get_account(&address).expect("token account exists");
    SplTokenAccount::unpack(&account.data)
        .expect("valid SPL Token account")
        .amount
}

fn read_order(svm: &LiteSVM, address: Pubkey) -> WorkOrderAccount {
    let account = svm.get_account(&address).expect("WorkOrder exists");
    let mut data = account.data.as_slice();
    WorkOrderAccount::try_deserialize(&mut data).expect("valid WorkOrder")
}

fn setup_verified(model: PaymentModel, status: VerificationStatus, bps: u16) -> Rig {
    let mut svm = LiteSVM::new().with_default_programs();
    let program = include_bytes!(concat!(
        env!("CARGO_TARGET_TMPDIR"),
        "/../deploy/aerosettle.so"
    ));
    svm.add_program(aerosettle::id(), program).unwrap();
    set_time(&mut svm, BASE_TIME);

    let protocol_authority = Keypair::new();
    let creator = Keypair::new();
    let verifier = Keypair::new();
    let owner = Keypair::new();
    let device = Keypair::new();
    for key in [&protocol_authority, &creator, &verifier, &owner, &device] {
        fund_lamports(&mut svm, key);
    }

    let protocol_config = pda(&[PROTOCOL_CONFIG_SEED]);
    must_send(
        &mut svm,
        &protocol_authority,
        instruction(
            aerosettle::instruction::InitializeProtocol {
                network_id: [9u8; 32],
                deployment_id: [10u8; 32],
            },
            aerosettle::accounts::InitializeProtocol {
                protocol_config,
                authority: protocol_authority.pubkey(),
                system_program: system_program::ID,
            },
        ),
    );

    let mint = make_mint(&mut svm, creator.pubkey(), TOTAL + BONUS);
    let source_tokens = make_token_account(&mut svm, mint, creator.pubkey(), TOTAL);
    let operator_tokens = make_token_account(&mut svm, mint, owner.pubkey(), 0);
    let refund_tokens = make_token_account(&mut svm, mint, creator.pubkey(), 0);

    let work_order_id = [201u8; 32];
    let work_order = pda(&[
        WORK_ORDER_SEED,
        protocol_config.as_ref(),
        creator.pubkey().as_ref(),
        work_order_id.as_ref(),
    ]);
    must_send(
        &mut svm,
        &creator,
        instruction(
            aerosettle::instruction::CreateWorkOrder {
                args: CreateWorkOrderArgs {
                    work_order_id,
                    work_type: WorkType::Inspection,
                    required_capabilities: Capability::AerialMobility.bit() | Capability::Gps.bit(),
                    evidence_requirements: EvidenceRequirement::Telemetry.bit()
                        | EvidenceRequirement::GpsTrace.bit()
                        | EvidenceRequirement::ImageManifest.bit()
                        | EvidenceRequirement::DeviceSignature.bit(),
                    manifest_hash: [44u8; 32],
                    settlement: SettlementTerms {
                        token_mint: mint,
                        total_amount: TOTAL,
                        payment_model: model,
                        verifier: verifier.pubkey(),
                    },
                    execution_deadline: BASE_TIME + 5_000,
                    verification_deadline: BASE_TIME + 10_000,
                },
            },
            aerosettle::accounts::CreateWorkOrder {
                protocol_config,
                work_order,
                creator: creator.pubkey(),
                system_program: system_program::ID,
            },
        ),
    );

    let vault = pda(&[ESCROW_VAULT_SEED, work_order.as_ref()]);
    must_send(
        &mut svm,
        &creator,
        instruction(
            aerosettle::instruction::FundWorkOrder {},
            aerosettle::accounts::FundWorkOrder {
                protocol_config,
                work_order,
                creator: creator.pubkey(),
                mint,
                creator_token_account: source_tokens,
                escrow_vault: vault,
                token_program: TOKEN_PROGRAM_ID,
                system_program: system_program::ID,
            },
        ),
    );
    assert_eq!(token_balance(&svm, vault), TOTAL);
    assert_eq!(read_order(&svm, work_order).status, WorkOrderStatus::Open);

    let agent_id = [202u8; 32];
    let agent_account = pda(&[AGENT_SEED, protocol_config.as_ref(), agent_id.as_ref()]);
    must_send(
        &mut svm,
        &owner,
        instruction(
            aerosettle::instruction::RegisterAgent {
                agent_id,
                signing_authority: device.pubkey(),
                agent_type: AgentType::Drone,
                capabilities: Capability::AerialMobility.bit()
                    | Capability::Gps.bit()
                    | Capability::Telemetry.bit(),
                metadata_hash: [45u8; 32],
            },
            aerosettle::accounts::RegisterAgent {
                protocol_config,
                agent_account,
                owner: owner.pubkey(),
                system_program: system_program::ID,
            },
        ),
    );
    must_send(
        &mut svm,
        &device,
        instruction(
            aerosettle::instruction::ClaimWorkOrder {},
            aerosettle::accounts::ClaimWorkOrder {
                protocol_config,
                work_order,
                agent_account,
                agent_signer: device.pubkey(),
            },
        ),
    );
    let claimed = read_order(&svm, work_order);
    assert_eq!(claimed.status, WorkOrderStatus::Claimed);
    assert_eq!(claimed.settlement_beneficiary, owner.pubkey());

    // Physical execution must finish after the claim and before submission.
    let submitted_at = claimed.claimed_at + 100;
    set_time(&mut svm, submitted_at);
    must_send(
        &mut svm,
        &device,
        instruction(
            aerosettle::instruction::SubmitExecution {
                args: SubmitExecutionArgs {
                    execution_receipt_hash: [101u8; 32],
                    evidence_manifest_hash: [102u8; 32],
                    provided_evidence: claimed.evidence_requirements,
                    execution_started_at: claimed.claimed_at,
                    execution_ended_at: claimed.claimed_at + 50,
                    signature_sequence: 0,
                },
            },
            aerosettle::accounts::SubmitExecution {
                protocol_config,
                work_order,
                agent_account,
                agent_signer: device.pubkey(),
            },
        ),
    );
    let submitted = read_order(&svm, work_order);
    assert_eq!(submitted.status, WorkOrderStatus::Submitted);

    let verified_at = submitted.submitted_at + 50;
    let attestation = VerificationAttestation::new(
        submitted.work_order_id,
        submitted.execution_receipt_hash,
        submitted.evidence_manifest_hash,
        verifier.pubkey(),
        status,
        bps,
        verified_at,
    );
    // CanonicalCommitment supplies commitment_hash().
    use aerosettle::CanonicalCommitment;

    let verify_ix = instruction(
        aerosettle::instruction::VerifyExecution {
            args: VerifyExecutionArgs {
                verification_attestation_hash: attestation.commitment_hash(),
                status,
                completion_bps: bps,
                verified_at,
            },
        },
        aerosettle::accounts::VerifyExecution {
            protocol_config,
            work_order,
            verifier: verifier.pubkey(),
        },
    );

    // Regression: reject a backdated attestation submitted
    // after the actual on-chain verification deadline.
    set_time(&mut svm, submitted.verification_deadline + 1);

    let late_result = send(&mut svm, &verifier, verify_ix.clone());

    assert!(
        late_result.is_err(),
        "Backdated verification must fail after deadline"
    );

    assert_eq!(
        read_order(&svm, work_order).status,
        WorkOrderStatus::Submitted
    );

    assert_eq!(token_balance(&svm, vault), TOTAL);

    // The identical instruction must succeed inside
    // the valid window. Refresh the blockhash to prevent
    // the earlier failed transaction from being reused.
    set_time(&mut svm, verified_at);
    svm.expire_blockhash();

    must_send(&mut svm, &verifier, verify_ix);
    let verified = read_order(&svm, work_order);
    assert_eq!(verified.status, WorkOrderStatus::Verified);
    assert_eq!(verified.settlement_beneficiary, owner.pubkey());
    assert_eq!(token_balance(&svm, vault), TOTAL);

    Rig {
        svm,
        owner,
        protocol_config,
        work_order,
        mint,
        vault,
        operator_tokens,
        refund_tokens,
    }
}

fn settle_instruction(rig: &Rig, operator_tokens: Pubkey, refund_tokens: Pubkey) -> Instruction {
    instruction(
        aerosettle::instruction::SettleWorkOrder {},
        aerosettle::accounts::SettleWorkOrder {
            protocol_config: rig.protocol_config,
            work_order: rig.work_order,
            escrow_vault: rig.vault,
            mint: rig.mint,
            operator_token_account: operator_tokens,
            creator_refund_token_account: refund_tokens,
            token_program: TOKEN_PROGRAM_ID,
        },
    )
}

fn execute_settlement(rig: &mut Rig) -> Result<(), String> {
    // A separate unrelated payer can permissionlessly finalize a verified order.
    let payer = Keypair::new();
    fund_lamports(&mut rig.svm, &payer);
    let ix = settle_instruction(rig, rig.operator_tokens, rig.refund_tokens);
    send(&mut rig.svm, &payer, ix)
}

fn must_settle(rig: &mut Rig) {
    let result = execute_settlement(rig);
    assert!(result.is_ok(), "settlement failed: {result:?}");
}

fn assert_distribution(rig: &Rig, operator: u64, refund: u64) {
    assert_eq!(token_balance(&rig.svm, rig.operator_tokens), operator);
    assert_eq!(token_balance(&rig.svm, rig.refund_tokens), refund);
    assert_eq!(token_balance(&rig.svm, rig.vault), 0);
    assert_eq!(
        read_order(&rig.svm, rig.work_order).status,
        WorkOrderStatus::Settled
    );
}

#[test]
fn proportional_7350_pays_operator_and_refunds_creator() {
    let mut rig = setup_verified(
        PaymentModel::Proportional,
        VerificationStatus::Accepted,
        7_350,
    );
    must_settle(&mut rig);
    assert_distribution(&rig, 73_500_000, 26_500_000);
}

#[test]
fn fixed_complete_pays_operator_fully() {
    let mut rig = setup_verified(PaymentModel::Fixed, VerificationStatus::Accepted, 10_000);
    must_settle(&mut rig);
    assert_distribution(&rig, TOTAL, 0);
}

#[test]
fn fixed_partial_refunds_creator_fully() {
    let mut rig = setup_verified(PaymentModel::Fixed, VerificationStatus::Accepted, 7_350);
    must_settle(&mut rig);
    assert_distribution(&rig, 0, TOTAL);
}

#[test]
fn rejected_refunds_creator_fully() {
    let mut rig = setup_verified(PaymentModel::Proportional, VerificationStatus::Rejected, 0);
    must_settle(&mut rig);
    assert_distribution(&rig, 0, TOTAL);
}

#[test]
fn unsolicited_surplus_is_returned_to_creator() {
    let mut rig = setup_verified(
        PaymentModel::Proportional,
        VerificationStatus::Accepted,
        7_350,
    );
    let donor = Keypair::new();
    fund_lamports(&mut rig.svm, &donor);
    // Mint fixture supply includes these 5 tokens, allocated to the donor here.
    let donor_tokens = make_token_account(&mut rig.svm, rig.mint, donor.pubkey(), BONUS);
    let donate = spl_instruction::transfer_checked(
        &TOKEN_PROGRAM_ID,
        &donor_tokens,
        &rig.mint,
        &rig.vault,
        &donor.pubkey(),
        &[],
        BONUS,
        DECIMALS,
    )
    .expect("donation instruction");
    must_send(&mut rig.svm, &donor, donate);
    assert_eq!(token_balance(&rig.svm, rig.vault), TOTAL + BONUS);
    must_settle(&mut rig);
    assert_distribution(&rig, 73_500_000, 26_500_000 + BONUS);
}

#[test]
fn wrong_beneficiary_account_cannot_redirect_payment() {
    let mut rig = setup_verified(
        PaymentModel::Proportional,
        VerificationStatus::Accepted,
        7_350,
    );
    let attacker = Keypair::new();
    let attack_tokens = make_token_account(&mut rig.svm, rig.mint, attacker.pubkey(), 0);
    let payer = Keypair::new();
    fund_lamports(&mut rig.svm, &payer);
    let ix = settle_instruction(&rig, attack_tokens, rig.refund_tokens);
    assert!(send(&mut rig.svm, &payer, ix).is_err());
    assert_eq!(token_balance(&rig.svm, rig.vault), TOTAL);
    assert_eq!(token_balance(&rig.svm, rig.operator_tokens), 0);
    assert_eq!(token_balance(&rig.svm, attack_tokens), 0);
    assert_eq!(
        read_order(&rig.svm, rig.work_order).status,
        WorkOrderStatus::Verified
    );
}

#[test]
fn wrong_mint_destination_is_rejected() {
    let mut rig = setup_verified(
        PaymentModel::Proportional,
        VerificationStatus::Accepted,
        7_350,
    );
    let wrong_mint = make_mint(&mut rig.svm, rig.owner.pubkey(), 0);
    let bad_operator = make_token_account(&mut rig.svm, wrong_mint, rig.owner.pubkey(), 0);
    let payer = Keypair::new();
    fund_lamports(&mut rig.svm, &payer);
    let ix = settle_instruction(&rig, bad_operator, rig.refund_tokens);
    assert!(send(&mut rig.svm, &payer, ix).is_err());
    assert_eq!(token_balance(&rig.svm, rig.vault), TOTAL);
    assert_eq!(
        read_order(&rig.svm, rig.work_order).status,
        WorkOrderStatus::Verified
    );
}

#[test]
fn second_settlement_cannot_pay_twice() {
    let mut rig = setup_verified(
        PaymentModel::Proportional,
        VerificationStatus::Accepted,
        7_350,
    );
    must_settle(&mut rig);
    let before_operator = token_balance(&rig.svm, rig.operator_tokens);
    let before_refund = token_balance(&rig.svm, rig.refund_tokens);
    rig.svm.expire_blockhash();
    assert!(execute_settlement(&mut rig).is_err());
    assert_distribution(&rig, before_operator, before_refund);
}

#[test]
fn frozen_refund_rolls_back_first_successful_cpi() {
    let mut rig = setup_verified(
        PaymentModel::Proportional,
        VerificationStatus::Accepted,
        7_350,
    );
    // Deliberately freeze the SECOND destination fixture, so CPI 1 can
    // execute but CPI 2 fails inside the Token Program.
    let mut account = rig.svm.get_account(&rig.refund_tokens).unwrap();
    let mut state = SplTokenAccount::unpack(&account.data).unwrap();
    state.state = AccountState::Frozen;
    SplTokenAccount::pack(state, &mut account.data).unwrap();
    rig.svm.set_account(rig.refund_tokens, account).unwrap();

    assert!(execute_settlement(&mut rig).is_err());
    assert_eq!(token_balance(&rig.svm, rig.operator_tokens), 0);
    assert_eq!(token_balance(&rig.svm, rig.refund_tokens), 0);
    assert_eq!(token_balance(&rig.svm, rig.vault), TOTAL);
    assert_eq!(
        read_order(&rig.svm, rig.work_order).status,
        WorkOrderStatus::Verified
    );
}

#[test]
fn insufficient_vault_balance_never_partially_settles() {
    let mut rig = setup_verified(
        PaymentModel::Proportional,
        VerificationStatus::Accepted,
        7_350,
    );
    // Controlled fixture corruption representing vault balance loss.
    let mut account = rig.svm.get_account(&rig.vault).unwrap();
    let mut state = SplTokenAccount::unpack(&account.data).unwrap();
    state.amount = TOTAL - 1;
    SplTokenAccount::pack(state, &mut account.data).unwrap();
    rig.svm.set_account(rig.vault, account).unwrap();

    assert!(execute_settlement(&mut rig).is_err());
    assert_eq!(token_balance(&rig.svm, rig.vault), TOTAL - 1);
    assert_eq!(token_balance(&rig.svm, rig.operator_tokens), 0);
    assert_eq!(token_balance(&rig.svm, rig.refund_tokens), 0);
    assert_eq!(
        read_order(&rig.svm, rig.work_order).status,
        WorkOrderStatus::Verified
    );
}

// -------------------- EPIC 2.8.5: escrow account cleanup --------------------

fn close_vault_instruction(
    rig: &Rig,
    creator: Pubkey,
    creator_refund_tokens: Pubkey,
) -> Instruction {
    instruction(
        aerosettle::instruction::CloseSettledVault {},
        aerosettle::accounts::CloseSettledVault {
            protocol_config: rig.protocol_config,
            work_order: rig.work_order,
            escrow_vault: rig.vault,
            mint: rig.mint,
            creator,
            creator_refund_token_account: creator_refund_tokens,
            token_program: TOKEN_PROGRAM_ID,
        },
    )
}

fn try_close_vault(
    rig: &mut Rig,
    creator: Pubkey,
    creator_refund_tokens: Pubkey,
) -> Result<(), String> {
    let payer = Keypair::new();
    fund_lamports(&mut rig.svm, &payer);
    let ix = close_vault_instruction(rig, creator, creator_refund_tokens);
    send(&mut rig.svm, &payer, ix)
}

fn try_close_default_vault(rig: &mut Rig, creator: Pubkey) -> Result<(), String> {
    let refund_tokens = rig.refund_tokens;
    try_close_vault(rig, creator, refund_tokens)
}

#[test]
fn settled_vault_closes_and_returns_rent_to_creator() {
    let mut rig = setup_verified(
        PaymentModel::Proportional,
        VerificationStatus::Accepted,
        7_350,
    );
    must_settle(&mut rig);
    let creator = read_order(&rig.svm, rig.work_order).creator;
    let vault_rent = rig.svm.get_account(&rig.vault).unwrap().lamports;
    let creator_lamports = rig.svm.get_account(&creator).unwrap().lamports;
    let before_refund = token_balance(&rig.svm, rig.refund_tokens);
    assert!(vault_rent > 0);

    assert!(try_close_default_vault(&mut rig, creator).is_ok());
    assert!(rig.svm.get_account(&rig.vault).is_none());
    assert_eq!(
        rig.svm.get_account(&creator).unwrap().lamports,
        creator_lamports + vault_rent
    );
    assert_eq!(token_balance(&rig.svm, rig.refund_tokens), before_refund);
    assert_eq!(
        read_order(&rig.svm, rig.work_order).status,
        WorkOrderStatus::Settled
    );
}

#[test]
fn cannot_close_vault_before_settlement() {
    let mut rig = setup_verified(
        PaymentModel::Proportional,
        VerificationStatus::Accepted,
        7_350,
    );
    let creator = read_order(&rig.svm, rig.work_order).creator;
    assert!(try_close_default_vault(&mut rig, creator).is_err());
    assert_eq!(token_balance(&rig.svm, rig.vault), TOTAL);
    assert_eq!(
        read_order(&rig.svm, rig.work_order).status,
        WorkOrderStatus::Verified
    );
}

#[test]
fn cannot_redirect_rent_to_unrelated_wallet() {
    let mut rig = setup_verified(
        PaymentModel::Proportional,
        VerificationStatus::Accepted,
        7_350,
    );
    must_settle(&mut rig);
    let attacker = Keypair::new();
    fund_lamports(&mut rig.svm, &attacker);
    let attacker_before = rig.svm.get_account(&attacker.pubkey()).unwrap().lamports;
    assert!(try_close_default_vault(&mut rig, attacker.pubkey()).is_err());
    assert_eq!(
        rig.svm.get_account(&attacker.pubkey()).unwrap().lamports,
        attacker_before
    );
    assert!(rig.svm.get_account(&rig.vault).is_some());
}

#[test]
fn cannot_redirect_post_settlement_refund() {
    let mut rig = setup_verified(
        PaymentModel::Proportional,
        VerificationStatus::Accepted,
        7_350,
    );
    must_settle(&mut rig);
    let creator = read_order(&rig.svm, rig.work_order).creator;
    let attacker = Keypair::new();
    let attacker_token_account = make_token_account(&mut rig.svm, rig.mint, attacker.pubkey(), 0);
    assert!(try_close_vault(&mut rig, creator, attacker_token_account).is_err());
    assert!(rig.svm.get_account(&rig.vault).is_some());
}

#[test]
fn post_settlement_donation_is_refunded_then_vault_closes() {
    let mut rig = setup_verified(
        PaymentModel::Proportional,
        VerificationStatus::Accepted,
        7_350,
    );
    must_settle(&mut rig);
    let creator = read_order(&rig.svm, rig.work_order).creator;
    let before_refund = token_balance(&rig.svm, rig.refund_tokens);
    let donor = Keypair::new();
    fund_lamports(&mut rig.svm, &donor);
    let donor_tokens = make_token_account(&mut rig.svm, rig.mint, donor.pubkey(), BONUS);
    let donate = spl_instruction::transfer_checked(
        &TOKEN_PROGRAM_ID,
        &donor_tokens,
        &rig.mint,
        &rig.vault,
        &donor.pubkey(),
        &[],
        BONUS,
        DECIMALS,
    )
    .unwrap();
    must_send(&mut rig.svm, &donor, donate);
    assert_eq!(token_balance(&rig.svm, rig.vault), BONUS);

    assert!(try_close_default_vault(&mut rig, creator).is_ok());
    assert!(rig.svm.get_account(&rig.vault).is_none());
    assert_eq!(
        token_balance(&rig.svm, rig.refund_tokens),
        before_refund + BONUS
    );
    assert_eq!(
        read_order(&rig.svm, rig.work_order).status,
        WorkOrderStatus::Settled
    );
}

#[test]
fn closed_vault_cannot_be_closed_twice() {
    let mut rig = setup_verified(
        PaymentModel::Proportional,
        VerificationStatus::Accepted,
        7_350,
    );
    must_settle(&mut rig);
    let creator = read_order(&rig.svm, rig.work_order).creator;
    assert!(try_close_default_vault(&mut rig, creator).is_ok());
    rig.svm.expire_blockhash();
    assert!(try_close_default_vault(&mut rig, creator).is_err());
    assert!(rig.svm.get_account(&rig.vault).is_none());
}
