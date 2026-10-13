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
    AgentAccount, AgentStatus, AgentType, Capability, ProtocolConfig, AEROSETTLE_PROTOCOL_VERSION,
    AGENT_SEED, PROTOCOL_CONFIG_SEED,
};

const TEST_NETWORK_ID: [u8; 32] = [9u8; 32];
const TEST_DEPLOYMENT_ID: [u8; 32] = [10u8; 32];

fn new_svm() -> LiteSVM {
    let program_id = aerosettle::id();

    let mut svm = LiteSVM::new();

    let program_bytes = include_bytes!(concat!(
        env!("CARGO_TARGET_TMPDIR"),
        "/../deploy/aerosettle.so"
    ));

    svm.add_program(program_id, program_bytes).unwrap();

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

fn protocol_config_pda() -> (Pubkey, u8) {
    Pubkey::find_program_address(&[PROTOCOL_CONFIG_SEED], &aerosettle::id())
}

fn agent_pda(protocol_config: &Pubkey, agent_id: &[u8; 32]) -> (Pubkey, u8) {
    Pubkey::find_program_address(
        &[AGENT_SEED, protocol_config.as_ref(), agent_id.as_ref()],
        &aerosettle::id(),
    )
}

fn initialize_protocol_instruction(
    authority: Pubkey,
    network_id: [u8; 32],
    deployment_id: [u8; 32],
) -> Instruction {
    let (protocol_config, _) = protocol_config_pda();

    Instruction::new_with_bytes(
        aerosettle::id(),
        &aerosettle::instruction::InitializeProtocol {
            network_id,
            deployment_id,
        }
        .data(),
        aerosettle::accounts::InitializeProtocol {
            protocol_config,
            authority,
            system_program: system_program::ID,
        }
        .to_account_metas(None),
    )
}

fn initialize_protocol(svm: &mut LiteSVM, authority: &Keypair) -> Pubkey {
    let (protocol_config, _) = protocol_config_pda();

    let instruction =
        initialize_protocol_instruction(authority.pubkey(), TEST_NETWORK_ID, TEST_DEPLOYMENT_ID);

    assert!(
        send_instruction(svm, authority, instruction,),
        "initialize_protocol should succeed"
    );

    protocol_config
}

#[allow(clippy::too_many_arguments)]
fn register_agent_instruction(
    protocol_config: Pubkey,
    owner: Pubkey,
    agent_id: [u8; 32],
    signing_authority: Pubkey,
    agent_type: AgentType,
    capabilities: u64,
    metadata_hash: [u8; 32],
) -> (Pubkey, Instruction) {
    let (agent_account, _) = agent_pda(&protocol_config, &agent_id);

    let instruction = Instruction::new_with_bytes(
        aerosettle::id(),
        &aerosettle::instruction::RegisterAgent {
            agent_id,
            signing_authority,
            agent_type,
            capabilities,
            metadata_hash,
        }
        .data(),
        aerosettle::accounts::RegisterAgent {
            protocol_config,
            agent_account,
            owner,
            system_program: system_program::ID,
        }
        .to_account_metas(None),
    );

    (agent_account, instruction)
}

fn read_protocol_config(svm: &LiteSVM, address: &Pubkey) -> ProtocolConfig {
    let account = svm
        .get_account(address)
        .expect("ProtocolConfig account must exist");

    assert_eq!(
        account.owner,
        aerosettle::id(),
        "ProtocolConfig must be owned by AeroSettle"
    );

    assert_eq!(
        account.data.len(),
        ProtocolConfig::SPACE,
        "ProtocolConfig account size changed unexpectedly"
    );

    let mut data: &[u8] = &account.data;

    ProtocolConfig::try_deserialize(&mut data).expect("ProtocolConfig must deserialize")
}

fn read_agent_account(svm: &LiteSVM, address: &Pubkey) -> AgentAccount {
    let account = svm.get_account(address).expect("AgentAccount must exist");

    assert_eq!(
        account.owner,
        aerosettle::id(),
        "AgentAccount must be owned by AeroSettle"
    );

    assert_eq!(
        account.data.len(),
        AgentAccount::SPACE,
        "AgentAccount size changed unexpectedly"
    );

    let mut data: &[u8] = &account.data;

    AgentAccount::try_deserialize(&mut data).expect("AgentAccount must deserialize")
}

#[test]
fn initialize_protocol_persists_correct_state() {
    let mut svm = new_svm();

    let authority = Keypair::new();
    fund(&mut svm, &authority);

    let protocol_config = initialize_protocol(&mut svm, &authority);

    let (_, expected_bump) = protocol_config_pda();

    let state = read_protocol_config(&svm, &protocol_config);

    assert_eq!(state.protocol_version, AEROSETTLE_PROTOCOL_VERSION);

    assert_eq!(state.authority, authority.pubkey());

    assert_eq!(state.network_id, TEST_NETWORK_ID);

    assert_eq!(state.deployment_id, TEST_DEPLOYMENT_ID);

    assert_eq!(state.program_id, aerosettle::id());

    assert_eq!(state.bump, expected_bump);

    assert_eq!(state.agent_count, 0);

    assert!(!state.paused);
}

#[test]
fn protocol_config_cannot_be_initialized_twice() {
    let mut svm = new_svm();

    let authority = Keypair::new();
    fund(&mut svm, &authority);

    let protocol_config = initialize_protocol(&mut svm, &authority);

    let duplicate_instruction =
        initialize_protocol_instruction(authority.pubkey(), TEST_NETWORK_ID, [99u8; 32]);

    assert!(
        !send_instruction(&mut svm, &authority, duplicate_instruction,),
        "second initialization must fail"
    );

    let state = read_protocol_config(&svm, &protocol_config);

    assert_eq!(
        state.deployment_id, TEST_DEPLOYMENT_ID,
        "failed reinitialization must not mutate state"
    );
}

#[test]
fn register_agent_persists_identity_and_increments_counter() {
    let mut svm = new_svm();

    let authority = Keypair::new();
    fund(&mut svm, &authority);

    let protocol_config = initialize_protocol(&mut svm, &authority);

    let owner = Keypair::new();
    fund(&mut svm, &owner);

    let signing_key = Keypair::new();

    let agent_id = [21u8; 32];

    let metadata_hash = [22u8; 32];

    let capabilities = Capability::AerialMobility.bit()
        | Capability::ThermalVision.bit()
        | Capability::Gps.bit()
        | Capability::Telemetry.bit();

    let (agent_account, instruction) = register_agent_instruction(
        protocol_config,
        owner.pubkey(),
        agent_id,
        signing_key.pubkey(),
        AgentType::Drone,
        capabilities,
        metadata_hash,
    );

    assert!(
        send_instruction(&mut svm, &owner, instruction,),
        "valid agent registration should succeed"
    );

    let (_, expected_bump) = agent_pda(&protocol_config, &agent_id);

    let agent = read_agent_account(&svm, &agent_account);

    assert_eq!(agent.protocol_version, AEROSETTLE_PROTOCOL_VERSION);

    assert_eq!(agent.protocol_config, protocol_config);

    assert_eq!(agent.agent_id, agent_id);

    assert_eq!(agent.owner, owner.pubkey());

    assert_eq!(agent.signing_authority, signing_key.pubkey());

    assert_eq!(agent.agent_type, AgentType::Drone);

    assert_eq!(agent.capabilities, capabilities);

    assert_eq!(agent.metadata_hash, metadata_hash);

    assert_eq!(agent.status, AgentStatus::Active);

    assert_eq!(agent.next_signature_sequence, 0);

    assert_eq!(agent.bump, expected_bump);

    let config = read_protocol_config(&svm, &protocol_config);

    assert_eq!(config.agent_count, 1);
}

#[test]
fn zero_agent_id_is_rejected_and_rolled_back() {
    let mut svm = new_svm();

    let authority = Keypair::new();
    fund(&mut svm, &authority);

    let protocol_config = initialize_protocol(&mut svm, &authority);

    let owner = Keypair::new();
    fund(&mut svm, &owner);

    let agent_id = [0u8; 32];

    let (agent_account, instruction) = register_agent_instruction(
        protocol_config,
        owner.pubkey(),
        agent_id,
        Keypair::new().pubkey(),
        AgentType::Drone,
        Capability::Gps.bit(),
        [31u8; 32],
    );

    assert!(!send_instruction(&mut svm, &owner, instruction,));

    assert!(
        svm.get_account(&agent_account).is_none(),
        "failed transaction must roll back PDA creation"
    );

    let config = read_protocol_config(&svm, &protocol_config);

    assert_eq!(config.agent_count, 0);
}

#[test]
fn zero_capabilities_are_rejected_and_rolled_back() {
    let mut svm = new_svm();

    let authority = Keypair::new();
    fund(&mut svm, &authority);

    let protocol_config = initialize_protocol(&mut svm, &authority);

    let owner = Keypair::new();
    fund(&mut svm, &owner);

    let agent_id = [41u8; 32];

    let (agent_account, instruction) = register_agent_instruction(
        protocol_config,
        owner.pubkey(),
        agent_id,
        Keypair::new().pubkey(),
        AgentType::IotSensor,
        0,
        [42u8; 32],
    );

    assert!(!send_instruction(&mut svm, &owner, instruction,));

    assert!(svm.get_account(&agent_account).is_none());

    let config = read_protocol_config(&svm, &protocol_config);

    assert_eq!(config.agent_count, 0);
}

#[test]
fn zero_metadata_hash_is_rejected_and_rolled_back() {
    let mut svm = new_svm();

    let authority = Keypair::new();
    fund(&mut svm, &authority);

    let protocol_config = initialize_protocol(&mut svm, &authority);

    let owner = Keypair::new();
    fund(&mut svm, &owner);

    let agent_id = [51u8; 32];

    let (agent_account, instruction) = register_agent_instruction(
        protocol_config,
        owner.pubkey(),
        agent_id,
        Keypair::new().pubkey(),
        AgentType::IotSensor,
        Capability::EnvironmentalSensing.bit(),
        [0u8; 32],
    );

    assert!(!send_instruction(&mut svm, &owner, instruction,));

    assert!(svm.get_account(&agent_account).is_none());

    let config = read_protocol_config(&svm, &protocol_config);

    assert_eq!(config.agent_count, 0);
}

#[test]
fn default_signing_authority_is_rejected() {
    let mut svm = new_svm();

    let authority = Keypair::new();
    fund(&mut svm, &authority);

    let protocol_config = initialize_protocol(&mut svm, &authority);

    let owner = Keypair::new();
    fund(&mut svm, &owner);

    let agent_id = [61u8; 32];

    let (agent_account, instruction) = register_agent_instruction(
        protocol_config,
        owner.pubkey(),
        agent_id,
        Pubkey::default(),
        AgentType::EdgeCompute,
        Capability::EdgeInference.bit(),
        [62u8; 32],
    );

    assert!(!send_instruction(&mut svm, &owner, instruction,));

    assert!(svm.get_account(&agent_account).is_none());
}

#[test]
fn same_agent_id_cannot_be_claimed_by_second_owner() {
    let mut svm = new_svm();

    let authority = Keypair::new();
    fund(&mut svm, &authority);

    let protocol_config = initialize_protocol(&mut svm, &authority);

    let first_owner = Keypair::new();

    let second_owner = Keypair::new();

    fund(&mut svm, &first_owner);

    fund(&mut svm, &second_owner);

    let agent_id = [71u8; 32];

    let original_metadata = [72u8; 32];

    let (agent_account, first_instruction) = register_agent_instruction(
        protocol_config,
        first_owner.pubkey(),
        agent_id,
        Keypair::new().pubkey(),
        AgentType::Drone,
        Capability::AerialMobility.bit() | Capability::Gps.bit(),
        original_metadata,
    );

    assert!(send_instruction(&mut svm, &first_owner, first_instruction,));

    let (_, second_instruction) = register_agent_instruction(
        protocol_config,
        second_owner.pubkey(),
        agent_id,
        Keypair::new().pubkey(),
        AgentType::Drone,
        Capability::AerialMobility.bit() | Capability::ThermalVision.bit(),
        [73u8; 32],
    );

    assert!(
        !send_instruction(&mut svm, &second_owner, second_instruction,),
        "same agent_id must not be registrable twice"
    );

    let agent = read_agent_account(&svm, &agent_account);

    assert_eq!(
        agent.owner,
        first_owner.pubkey(),
        "failed takeover must preserve original owner"
    );

    assert_eq!(agent.metadata_hash, original_metadata);

    let config = read_protocol_config(&svm, &protocol_config);

    assert_eq!(
        config.agent_count, 1,
        "failed duplicate registration must not increment counter"
    );
}
