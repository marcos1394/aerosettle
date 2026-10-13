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
    AgentAccount, AgentStatus, AgentType, Capability, ProtocolConfig, AGENT_SEED,
    PROTOCOL_CONFIG_SEED,
};

const TEST_NETWORK_ID: [u8; 32] = [9u8; 32];
const TEST_DEPLOYMENT_ID: [u8; 32] = [10u8; 32];

struct Fixture {
    svm: LiteSVM,
    authority: Keypair,
    owner: Keypair,
    protocol_config: Pubkey,
    agent_account: Pubkey,
    agent_id: [u8; 32],
    initial_signing_authority: Pubkey,
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
    send_instruction_with_signers(svm, payer, instruction, &[payer])
}

fn send_instruction_with_signers(
    svm: &mut LiteSVM,
    payer: &Keypair,
    instruction: Instruction,
    signers: &[&Keypair],
) -> bool {
    let blockhash = svm.latest_blockhash();

    let message = Message::new_with_blockhash(&[instruction], Some(&payer.pubkey()), &blockhash);

    let transaction =
        VersionedTransaction::try_new(VersionedMessage::Legacy(message), signers).unwrap();

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

fn initialize_protocol_instruction(authority: Pubkey) -> Instruction {
    let protocol_config = protocol_config_pda();

    Instruction::new_with_bytes(
        aerosettle::id(),
        &aerosettle::instruction::InitializeProtocol {
            network_id: TEST_NETWORK_ID,
            deployment_id: TEST_DEPLOYMENT_ID,
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

fn register_agent_instruction(
    protocol_config: Pubkey,
    owner: Pubkey,
    agent_id: [u8; 32],
    signing_authority: Pubkey,
) -> (Pubkey, Instruction) {
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
            metadata_hash: [22u8; 32],
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

fn suspend_instruction(
    protocol_config: Pubkey,
    agent_account: Pubkey,
    actor: Pubkey,
) -> Instruction {
    Instruction::new_with_bytes(
        aerosettle::id(),
        &aerosettle::instruction::SuspendAgent {}.data(),
        aerosettle::accounts::ManageAgent {
            protocol_config,
            agent_account,
            actor,
        }
        .to_account_metas(None),
    )
}

fn reactivate_instruction(
    protocol_config: Pubkey,
    agent_account: Pubkey,
    actor: Pubkey,
) -> Instruction {
    Instruction::new_with_bytes(
        aerosettle::id(),
        &aerosettle::instruction::ReactivateAgent {}.data(),
        aerosettle::accounts::ManageAgent {
            protocol_config,
            agent_account,
            actor,
        }
        .to_account_metas(None),
    )
}

fn revoke_instruction(
    protocol_config: Pubkey,
    agent_account: Pubkey,
    actor: Pubkey,
) -> Instruction {
    Instruction::new_with_bytes(
        aerosettle::id(),
        &aerosettle::instruction::RevokeAgent {}.data(),
        aerosettle::accounts::ManageAgent {
            protocol_config,
            agent_account,
            actor,
        }
        .to_account_metas(None),
    )
}

fn rotate_key_instruction(
    protocol_config: Pubkey,
    agent_account: Pubkey,
    owner: Pubkey,
    new_signing_authority: Pubkey,
) -> Instruction {
    Instruction::new_with_bytes(
        aerosettle::id(),
        &aerosettle::instruction::RotateSigningAuthority {
            new_signing_authority,
        }
        .data(),
        aerosettle::accounts::OwnerManageAgent {
            protocol_config,
            agent_account,
            owner,
        }
        .to_account_metas(None),
    )
}

fn update_metadata_instruction(
    protocol_config: Pubkey,
    agent_account: Pubkey,
    owner: Pubkey,
    metadata_hash: [u8; 32],
) -> Instruction {
    Instruction::new_with_bytes(
        aerosettle::id(),
        &aerosettle::instruction::UpdateAgentMetadata { metadata_hash }.data(),
        aerosettle::accounts::OwnerManageAgent {
            protocol_config,
            agent_account,
            owner,
        }
        .to_account_metas(None),
    )
}

fn update_capabilities_instruction(
    protocol_config: Pubkey,
    agent_account: Pubkey,
    owner: Pubkey,
    capabilities: u64,
) -> Instruction {
    Instruction::new_with_bytes(
        aerosettle::id(),
        &aerosettle::instruction::UpdateAgentCapabilities { capabilities }.data(),
        aerosettle::accounts::OwnerManageAgent {
            protocol_config,
            agent_account,
            owner,
        }
        .to_account_metas(None),
    )
}

fn transfer_instruction(
    protocol_config: Pubkey,
    agent_account: Pubkey,
    current_owner: Pubkey,
    new_owner: Pubkey,
    new_signing_authority: Pubkey,
) -> Instruction {
    Instruction::new_with_bytes(
        aerosettle::id(),
        &aerosettle::instruction::TransferAgentOwnership {
            new_signing_authority,
        }
        .data(),
        aerosettle::accounts::TransferAgentOwnership {
            protocol_config,
            agent_account,
            current_owner,
            new_owner,
        }
        .to_account_metas(None),
    )
}

fn read_agent(svm: &LiteSVM, address: &Pubkey) -> AgentAccount {
    let account = svm.get_account(address).expect("AgentAccount must exist");

    let mut data: &[u8] = &account.data;

    AgentAccount::try_deserialize(&mut data).expect("AgentAccount must deserialize")
}

fn read_config(svm: &LiteSVM, address: &Pubkey) -> ProtocolConfig {
    let account = svm.get_account(address).expect("ProtocolConfig must exist");

    let mut data: &[u8] = &account.data;

    ProtocolConfig::try_deserialize(&mut data).expect("ProtocolConfig must deserialize")
}

fn fixture() -> Fixture {
    let mut svm = new_svm();

    let authority = Keypair::new();

    fund(&mut svm, &authority);

    let initialize = initialize_protocol_instruction(authority.pubkey());

    assert!(send_instruction(&mut svm, &authority, initialize,));

    let protocol_config = protocol_config_pda();

    let owner = Keypair::new();

    fund(&mut svm, &owner);

    let device_key = Keypair::new();

    let agent_id = [21u8; 32];

    let (agent_account, register) = register_agent_instruction(
        protocol_config,
        owner.pubkey(),
        agent_id,
        device_key.pubkey(),
    );

    assert!(send_instruction(&mut svm, &owner, register,));

    Fixture {
        svm,
        authority,
        owner,
        protocol_config,
        agent_account,
        agent_id,
        initial_signing_authority: device_key.pubkey(),
    }
}

#[test]
fn owner_can_suspend_and_reactivate_agent() {
    let mut fx = fixture();

    let suspend = suspend_instruction(fx.protocol_config, fx.agent_account, fx.owner.pubkey());

    assert!(send_instruction(&mut fx.svm, &fx.owner, suspend,));

    let suspended = read_agent(&fx.svm, &fx.agent_account);

    assert_eq!(suspended.status, AgentStatus::OwnerSuspended);

    let reactivate =
        reactivate_instruction(fx.protocol_config, fx.agent_account, fx.owner.pubkey());

    assert!(send_instruction(&mut fx.svm, &fx.owner, reactivate,));

    let active = read_agent(&fx.svm, &fx.agent_account);

    assert_eq!(active.status, AgentStatus::Active);
}

#[test]
fn unauthorized_third_party_cannot_suspend_agent() {
    let mut fx = fixture();

    let attacker = Keypair::new();

    fund(&mut fx.svm, &attacker);

    let suspend = suspend_instruction(fx.protocol_config, fx.agent_account, attacker.pubkey());

    assert!(!send_instruction(&mut fx.svm, &attacker, suspend,));

    assert_eq!(
        read_agent(&fx.svm, &fx.agent_account).status,
        AgentStatus::Active
    );
}

#[test]
fn admin_suspension_cannot_be_reversed_by_owner() {
    let mut fx = fixture();

    let suspend = suspend_instruction(fx.protocol_config, fx.agent_account, fx.authority.pubkey());

    assert!(send_instruction(&mut fx.svm, &fx.authority, suspend,));

    assert_eq!(
        read_agent(&fx.svm, &fx.agent_account).status,
        AgentStatus::AdminSuspended
    );

    let owner_reactivate =
        reactivate_instruction(fx.protocol_config, fx.agent_account, fx.owner.pubkey());

    assert!(!send_instruction(&mut fx.svm, &fx.owner, owner_reactivate,));

    assert_eq!(
        read_agent(&fx.svm, &fx.agent_account).status,
        AgentStatus::AdminSuspended
    );

    let admin_reactivate =
        reactivate_instruction(fx.protocol_config, fx.agent_account, fx.authority.pubkey());

    assert!(send_instruction(
        &mut fx.svm,
        &fx.authority,
        admin_reactivate,
    ));

    assert_eq!(
        read_agent(&fx.svm, &fx.agent_account).status,
        AgentStatus::Active
    );
}

#[test]
fn admin_can_escalate_owner_suspension() {
    let mut fx = fixture();

    let owner_suspend =
        suspend_instruction(fx.protocol_config, fx.agent_account, fx.owner.pubkey());

    assert!(send_instruction(&mut fx.svm, &fx.owner, owner_suspend,));

    let admin_suspend =
        suspend_instruction(fx.protocol_config, fx.agent_account, fx.authority.pubkey());

    assert!(send_instruction(&mut fx.svm, &fx.authority, admin_suspend,));

    assert_eq!(
        read_agent(&fx.svm, &fx.agent_account).status,
        AgentStatus::AdminSuspended
    );
}

#[test]
fn only_protocol_authority_can_revoke_agent() {
    let mut fx = fixture();

    let owner_revoke = revoke_instruction(fx.protocol_config, fx.agent_account, fx.owner.pubkey());

    assert!(!send_instruction(&mut fx.svm, &fx.owner, owner_revoke,));

    assert_eq!(
        read_agent(&fx.svm, &fx.agent_account).status,
        AgentStatus::Active
    );

    let admin_revoke =
        revoke_instruction(fx.protocol_config, fx.agent_account, fx.authority.pubkey());

    assert!(send_instruction(&mut fx.svm, &fx.authority, admin_revoke,));

    assert_eq!(
        read_agent(&fx.svm, &fx.agent_account).status,
        AgentStatus::Revoked
    );
}

#[test]
fn revoked_agent_cannot_be_reactivated() {
    let mut fx = fixture();

    let revoke = revoke_instruction(fx.protocol_config, fx.agent_account, fx.authority.pubkey());

    assert!(send_instruction(&mut fx.svm, &fx.authority, revoke,));

    let reactivate =
        reactivate_instruction(fx.protocol_config, fx.agent_account, fx.authority.pubkey());

    assert!(!send_instruction(&mut fx.svm, &fx.authority, reactivate,));

    assert_eq!(
        read_agent(&fx.svm, &fx.agent_account).status,
        AgentStatus::Revoked
    );
}

#[test]
fn owner_can_rotate_device_signing_authority() {
    let mut fx = fixture();

    let new_device_key = Keypair::new();

    let rotate = rotate_key_instruction(
        fx.protocol_config,
        fx.agent_account,
        fx.owner.pubkey(),
        new_device_key.pubkey(),
    );

    assert!(send_instruction(&mut fx.svm, &fx.owner, rotate,));

    let agent = read_agent(&fx.svm, &fx.agent_account);

    assert_ne!(agent.signing_authority, fx.initial_signing_authority);

    assert_eq!(agent.signing_authority, new_device_key.pubkey());
}

#[test]
fn third_party_cannot_rotate_device_key() {
    let mut fx = fixture();

    let attacker = Keypair::new();

    fund(&mut fx.svm, &attacker);

    let rotate = rotate_key_instruction(
        fx.protocol_config,
        fx.agent_account,
        attacker.pubkey(),
        Keypair::new().pubkey(),
    );

    assert!(!send_instruction(&mut fx.svm, &attacker, rotate,));

    assert_eq!(
        read_agent(&fx.svm, &fx.agent_account).signing_authority,
        fx.initial_signing_authority
    );
}

#[test]
fn owner_can_update_metadata_and_capabilities() {
    let mut fx = fixture();

    let new_metadata = [88u8; 32];

    let update_metadata = update_metadata_instruction(
        fx.protocol_config,
        fx.agent_account,
        fx.owner.pubkey(),
        new_metadata,
    );

    assert!(send_instruction(&mut fx.svm, &fx.owner, update_metadata,));

    let new_capabilities = Capability::AerialMobility.bit()
        | Capability::Gps.bit()
        | Capability::ThermalVision.bit()
        | Capability::EdgeInference.bit();

    let update_capabilities = update_capabilities_instruction(
        fx.protocol_config,
        fx.agent_account,
        fx.owner.pubkey(),
        new_capabilities,
    );

    assert!(send_instruction(
        &mut fx.svm,
        &fx.owner,
        update_capabilities,
    ));

    let agent = read_agent(&fx.svm, &fx.agent_account);

    assert_eq!(agent.metadata_hash, new_metadata);

    assert_eq!(agent.capabilities, new_capabilities);
}

#[test]
fn transfer_requires_new_owner_signature() {
    let fx = fixture();

    let new_owner = Keypair::new();

    let new_device_key = Keypair::new();

    let transfer = transfer_instruction(
        fx.protocol_config,
        fx.agent_account,
        fx.owner.pubkey(),
        new_owner.pubkey(),
        new_device_key.pubkey(),
    );

    let blockhash = fx.svm.latest_blockhash();

    let message = Message::new_with_blockhash(&[transfer], Some(&fx.owner.pubkey()), &blockhash);

    let result = VersionedTransaction::try_new(VersionedMessage::Legacy(message), &[&fx.owner]);

    assert!(
        result.is_err(),
        "transaction must require the new owner's signature"
    );
}

#[test]
fn valid_transfer_preserves_agent_identity_and_pda() {
    let mut fx = fixture();

    let original_pda = fx.agent_account;

    let original_agent = read_agent(&fx.svm, &fx.agent_account);

    let new_owner = Keypair::new();

    fund(&mut fx.svm, &new_owner);

    let new_device_key = Keypair::new();

    let transfer = transfer_instruction(
        fx.protocol_config,
        fx.agent_account,
        fx.owner.pubkey(),
        new_owner.pubkey(),
        new_device_key.pubkey(),
    );

    assert!(send_instruction_with_signers(
        &mut fx.svm,
        &fx.owner,
        transfer,
        &[&fx.owner, &new_owner],
    ));

    let agent = read_agent(&fx.svm, &original_pda);

    assert_eq!(agent.agent_id, fx.agent_id);

    assert_eq!(agent.owner, new_owner.pubkey());

    assert_eq!(agent.signing_authority, new_device_key.pubkey());

    assert_eq!(
        original_pda,
        agent_pda(&fx.protocol_config, &fx.agent_id),
        "ownership transfer must not change agent PDA"
    );

    assert_eq!(
        agent.registered_at, original_agent.registered_at,
        "historical identity must be preserved"
    );

    let config = read_config(&fx.svm, &fx.protocol_config);

    assert_eq!(
        config.agent_count, 1,
        "ownership transfer must not create another agent"
    );
}

#[test]
fn revoked_agent_rejects_mutations_and_transfer() {
    let mut fx = fixture();

    let revoke = revoke_instruction(fx.protocol_config, fx.agent_account, fx.authority.pubkey());

    assert!(send_instruction(&mut fx.svm, &fx.authority, revoke,));

    let rotate = rotate_key_instruction(
        fx.protocol_config,
        fx.agent_account,
        fx.owner.pubkey(),
        Keypair::new().pubkey(),
    );

    assert!(!send_instruction(&mut fx.svm, &fx.owner, rotate,));

    let metadata_update = update_metadata_instruction(
        fx.protocol_config,
        fx.agent_account,
        fx.owner.pubkey(),
        [99u8; 32],
    );

    assert!(!send_instruction(&mut fx.svm, &fx.owner, metadata_update,));

    let new_owner = Keypair::new();

    fund(&mut fx.svm, &new_owner);

    let transfer = transfer_instruction(
        fx.protocol_config,
        fx.agent_account,
        fx.owner.pubkey(),
        new_owner.pubkey(),
        Keypair::new().pubkey(),
    );

    assert!(!send_instruction_with_signers(
        &mut fx.svm,
        &fx.owner,
        transfer,
        &[&fx.owner, &new_owner],
    ));

    let agent = read_agent(&fx.svm, &fx.agent_account);

    assert_eq!(agent.status, AgentStatus::Revoked);

    assert_eq!(agent.owner, fx.owner.pubkey());

    assert_eq!(agent.signing_authority, fx.initial_signing_authority);
}
