use {
    anchor_lang::{
        prelude::Pubkey,
        solana_program::{instruction::Instruction, system_program},
        AccountDeserialize, InstructionData, ToAccountMetas,
    },
    litesvm::LiteSVM,
    solana_keypair::Keypair,
    solana_message::{Message, VersionedMessage},
    solana_signer::Signer,
    solana_transaction::versioned::VersionedTransaction,
};

use aerosettle::{
    AgentType, Capability, CreateWorkOrderArgs, EvidenceRequirement, PaymentModel, SettlementTerms,
    WorkOrderAccount, WorkOrderStatus, WorkType, AGENT_SEED, PROTOCOL_CONFIG_SEED, WORK_ORDER_SEED,
};

const TEST_NETWORK_ID: [u8; 32] = [9u8; 32];
const TEST_DEPLOYMENT_ID: [u8; 32] = [10u8; 32];

const FUTURE_EXECUTION_DEADLINE: i64 = i64::MAX - 1;
const FUTURE_VERIFICATION_DEADLINE: i64 = i64::MAX;

fn pubkey(value: u8) -> Pubkey {
    Pubkey::new_from_array([value; 32])
}

fn new_svm() -> LiteSVM {
    let mut svm = LiteSVM::new();

    let program_bytes = include_bytes!(concat!(
        env!("CARGO_TARGET_TMPDIR"),
        "/../deploy/aerosettle.so"
    ));

    svm.add_program(aerosettle::id(), program_bytes).unwrap();

    svm
}

fn fund(svm: &mut LiteSVM, keypair: &Keypair) {
    svm.airdrop(&keypair.pubkey(), 5_000_000_000).unwrap();
}

fn send_instruction(svm: &mut LiteSVM, payer: &Keypair, instruction: Instruction) -> bool {
    let blockhash = svm.latest_blockhash();

    let message = Message::new_with_blockhash(&[instruction], Some(&payer.pubkey()), &blockhash);

    let transaction =
        VersionedTransaction::try_new(VersionedMessage::Legacy(message), &[payer]).unwrap();

    svm.send_transaction(transaction).is_ok()
}

fn protocol_config_pda() -> Pubkey {
    Pubkey::find_program_address(&[PROTOCOL_CONFIG_SEED], &aerosettle::id()).0
}

fn agent_pda(protocol_config: &Pubkey, agent_id: &[u8; 32]) -> Pubkey {
    Pubkey::find_program_address(
        &[AGENT_SEED, protocol_config.as_ref(), agent_id.as_ref()],
        &aerosettle::id(),
    )
    .0
}

fn work_order_pda(protocol_config: &Pubkey, creator: &Pubkey, work_order_id: &[u8; 32]) -> Pubkey {
    Pubkey::find_program_address(
        &[
            WORK_ORDER_SEED,
            protocol_config.as_ref(),
            creator.as_ref(),
            work_order_id.as_ref(),
        ],
        &aerosettle::id(),
    )
    .0
}

fn initialize_protocol(svm: &mut LiteSVM, authority: &Keypair) -> Pubkey {
    let protocol_config = protocol_config_pda();

    let instruction = Instruction::new_with_bytes(
        aerosettle::id(),
        &aerosettle::instruction::InitializeProtocol {
            network_id: TEST_NETWORK_ID,
            deployment_id: TEST_DEPLOYMENT_ID,
        }
        .data(),
        aerosettle::accounts::InitializeProtocol {
            protocol_config,
            authority: authority.pubkey(),
            system_program: system_program::ID,
        }
        .to_account_metas(None),
    );

    assert!(
        send_instruction(svm, authority, instruction,),
        "protocol initialization must succeed"
    );

    protocol_config
}

fn valid_args(work_order_id: [u8; 32]) -> CreateWorkOrderArgs {
    CreateWorkOrderArgs {
        work_order_id,
        work_type: WorkType::Inspection,

        required_capabilities: Capability::AerialMobility.bit() | Capability::Gps.bit(),

        evidence_requirements: EvidenceRequirement::Telemetry.bit()
            | EvidenceRequirement::GpsTrace.bit()
            | EvidenceRequirement::ImageManifest.bit()
            | EvidenceRequirement::DeviceSignature.bit(),

        manifest_hash: [40u8; 32],

        settlement: SettlementTerms {
            token_mint: pubkey(41),
            total_amount: 100_000_000,
            payment_model: PaymentModel::Proportional,
            verifier: pubkey(42),
        },

        execution_deadline: FUTURE_EXECUTION_DEADLINE,

        verification_deadline: FUTURE_VERIFICATION_DEADLINE,
    }
}

fn create_work_order_instruction(
    protocol_config: Pubkey,
    creator: Pubkey,
    args: CreateWorkOrderArgs,
) -> (Pubkey, Instruction) {
    let work_order = work_order_pda(&protocol_config, &creator, &args.work_order_id);

    let instruction = Instruction::new_with_bytes(
        aerosettle::id(),
        &aerosettle::instruction::CreateWorkOrder { args }.data(),
        aerosettle::accounts::CreateWorkOrder {
            protocol_config,
            work_order,
            creator,
            system_program: system_program::ID,
        }
        .to_account_metas(None),
    );

    (work_order, instruction)
}

fn register_agent(
    svm: &mut LiteSVM,
    protocol_config: Pubkey,
    owner: &Keypair,
    signing_authority: Pubkey,
    agent_id: [u8; 32],
) -> Pubkey {
    let agent_account = agent_pda(&protocol_config, &agent_id);

    let capabilities =
        Capability::AerialMobility.bit() | Capability::Gps.bit() | Capability::Telemetry.bit();

    let instruction = Instruction::new_with_bytes(
        aerosettle::id(),
        &aerosettle::instruction::RegisterAgent {
            agent_id,
            signing_authority,
            agent_type: AgentType::Drone,
            capabilities,
            metadata_hash: [55u8; 32],
        }
        .data(),
        aerosettle::accounts::RegisterAgent {
            protocol_config,
            agent_account,
            owner: owner.pubkey(),
            system_program: system_program::ID,
        }
        .to_account_metas(None),
    );

    assert!(
        send_instruction(svm, owner, instruction,),
        "agent registration must succeed"
    );

    agent_account
}

fn claim_instruction(
    protocol_config: Pubkey,
    work_order: Pubkey,
    agent_account: Pubkey,
    agent_signer: Pubkey,
) -> Instruction {
    Instruction::new_with_bytes(
        aerosettle::id(),
        &aerosettle::instruction::ClaimWorkOrder {}.data(),
        aerosettle::accounts::ClaimWorkOrder {
            protocol_config,
            work_order,
            agent_account,
            agent_signer,
        }
        .to_account_metas(None),
    )
}

fn read_work_order(svm: &LiteSVM, address: &Pubkey) -> WorkOrderAccount {
    let account = svm
        .get_account(address)
        .expect("WorkOrderAccount must exist");

    assert_eq!(account.owner, aerosettle::id());

    assert_eq!(account.data.len(), WorkOrderAccount::SPACE);

    let mut data: &[u8] = &account.data;

    WorkOrderAccount::try_deserialize(&mut data).expect("WorkOrderAccount must deserialize")
}

fn assert_creation_rejected(args: CreateWorkOrderArgs) {
    let mut svm = new_svm();

    let authority = Keypair::new();

    fund(&mut svm, &authority);

    let protocol_config = initialize_protocol(&mut svm, &authority);

    let creator = Keypair::new();

    fund(&mut svm, &creator);

    let (work_order, instruction) =
        create_work_order_instruction(protocol_config, creator.pubkey(), args);

    assert!(
        !send_instruction(&mut svm, &creator, instruction,),
        "invalid WorkOrder creation must fail"
    );

    assert!(
        svm.get_account(&work_order).is_none(),
        "failed creation must roll back PDA creation"
    );
}

#[test]
fn valid_work_order_is_persisted_as_draft() {
    let mut svm = new_svm();

    let authority = Keypair::new();

    fund(&mut svm, &authority);

    let protocol_config = initialize_protocol(&mut svm, &authority);

    let creator = Keypair::new();

    fund(&mut svm, &creator);

    let args = valid_args([1u8; 32]);

    let expected = args.clone();

    let (work_order_address, instruction) =
        create_work_order_instruction(protocol_config, creator.pubkey(), args);

    assert!(send_instruction(&mut svm, &creator, instruction,));

    let order = read_work_order(&svm, &work_order_address);

    assert_eq!(order.protocol_config, protocol_config);

    assert_eq!(order.creator, creator.pubkey());

    assert_eq!(order.work_order_id, expected.work_order_id);

    assert_eq!(order.work_type, expected.work_type);

    assert_eq!(order.required_capabilities, expected.required_capabilities);

    assert_eq!(order.evidence_requirements, expected.evidence_requirements);

    assert_eq!(order.manifest_hash, expected.manifest_hash);

    assert_eq!(order.token_mint, expected.settlement.token_mint);

    assert_eq!(order.total_amount, expected.settlement.total_amount);

    assert_eq!(order.payment_model, expected.settlement.payment_model);

    assert_eq!(order.verifier, expected.settlement.verifier);

    assert_eq!(order.execution_deadline, expected.execution_deadline);

    assert_eq!(order.verification_deadline, expected.verification_deadline);

    assert_eq!(order.status, WorkOrderStatus::Draft);

    assert_eq!(order.claimed_agent, Pubkey::default());

    assert_eq!(order.claimed_at, 0);

    assert_eq!(order.submitted_at, 0);

    assert_eq!(order.verified_at, 0);

    assert_eq!(order.settled_at, 0);
}

#[test]
fn duplicate_work_order_pda_is_rejected() {
    let mut svm = new_svm();

    let authority = Keypair::new();

    fund(&mut svm, &authority);

    let protocol_config = initialize_protocol(&mut svm, &authority);

    let creator = Keypair::new();

    fund(&mut svm, &creator);

    let args = valid_args([2u8; 32]);

    let (work_order_address, first_instruction) =
        create_work_order_instruction(protocol_config, creator.pubkey(), args.clone());

    assert!(send_instruction(&mut svm, &creator, first_instruction,));

    // Same PDA seeds, but different transaction data so this is not merely
    // rejected as an identical transaction signature.
    let mut duplicate_args = args;

    duplicate_args.manifest_hash = [99u8; 32];

    let (duplicate_address, duplicate_instruction) =
        create_work_order_instruction(protocol_config, creator.pubkey(), duplicate_args);

    assert_eq!(duplicate_address, work_order_address);

    assert!(
        !send_instruction(&mut svm, &creator, duplicate_instruction,),
        "same creator + work_order_id must resolve to an existing PDA"
    );

    let persisted = read_work_order(&svm, &work_order_address);

    assert_eq!(
        persisted.manifest_hash, [40u8; 32],
        "failed duplicate must not mutate original WorkOrder"
    );
}

#[test]
fn zero_work_order_id_is_rejected() {
    assert_creation_rejected(valid_args([0u8; 32]));
}

#[test]
fn zero_required_capabilities_are_rejected() {
    let mut args = valid_args([3u8; 32]);

    args.required_capabilities = 0;

    assert_creation_rejected(args);
}

#[test]
fn zero_evidence_requirements_are_rejected() {
    let mut args = valid_args([4u8; 32]);

    args.evidence_requirements = 0;

    assert_creation_rejected(args);
}

#[test]
fn zero_manifest_hash_is_rejected() {
    let mut args = valid_args([5u8; 32]);

    args.manifest_hash = [0u8; 32];

    assert_creation_rejected(args);
}

#[test]
fn default_token_mint_is_rejected() {
    let mut args = valid_args([6u8; 32]);

    args.settlement.token_mint = Pubkey::default();

    assert_creation_rejected(args);
}

#[test]
fn default_verifier_is_rejected() {
    let mut args = valid_args([7u8; 32]);

    args.settlement.verifier = Pubkey::default();

    assert_creation_rejected(args);
}

#[test]
fn zero_settlement_amount_is_rejected() {
    let mut args = valid_args([8u8; 32]);

    args.settlement.total_amount = 0;

    assert_creation_rejected(args);
}

#[test]
fn invalid_deadline_order_is_rejected() {
    let mut args = valid_args([9u8; 32]);

    args.execution_deadline = 10_000;
    args.verification_deadline = 9_999;

    assert_creation_rejected(args);
}

#[test]
fn draft_work_order_cannot_be_claimed() {
    let mut svm = new_svm();

    let authority = Keypair::new();

    fund(&mut svm, &authority);

    let protocol_config = initialize_protocol(&mut svm, &authority);

    let creator = Keypair::new();

    fund(&mut svm, &creator);

    let (work_order, create_instruction) =
        create_work_order_instruction(protocol_config, creator.pubkey(), valid_args([10u8; 32]));

    assert!(send_instruction(&mut svm, &creator, create_instruction,));

    let owner = Keypair::new();

    fund(&mut svm, &owner);

    let device_key = Keypair::new();

    // The device is the payer/signer of claim_work_order.
    fund(&mut svm, &device_key);

    let agent_account = register_agent(
        &mut svm,
        protocol_config,
        &owner,
        device_key.pubkey(),
        [20u8; 32],
    );

    let claim = claim_instruction(
        protocol_config,
        work_order,
        agent_account,
        device_key.pubkey(),
    );

    assert!(
        !send_instruction(&mut svm, &device_key, claim,),
        "Draft WorkOrder must never be claimable"
    );

    let order = read_work_order(&svm, &work_order);

    assert_eq!(order.status, WorkOrderStatus::Draft);

    assert_eq!(order.claimed_agent, Pubkey::default());

    assert_eq!(order.claimed_at, 0);
}
