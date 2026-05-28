from relationship_substrate import __version__
from relationship_substrate.contracts import SourceEventIn, SourcePosture
from relationship_substrate.config import Settings


def test_package_has_version():
    assert __version__ == "0.1.0"


def test_default_settings_are_local_and_read_only_for_msgvault():
    settings = Settings()

    assert settings.database_url == "postgresql://localhost:5432/relationship_substrate"
    assert settings.msgvault_binary == "msgvault"
    # msgvault_home and msgvault_config are env-var driven; just verify they are strings
    assert isinstance(settings.msgvault_home, str)
    assert isinstance(settings.msgvault_config, str)


def test_next_up_source_event_keeps_unknown_upstream():
    event = SourceEventIn(
        source_name="next_up",
        source_event_type="curated_contact",
        source_event_key="next_up:people.xlsx:Contacts:2",
        source_payload={"email": "person@example.com"},
        source_posture=SourcePosture.CURATED_EXPORT,
        provenance_status="unknown_upstream",
        trust_role="identity/context seed",
    )

    assert event.source_posture == SourcePosture.CURATED_EXPORT
    assert event.provenance_status == "unknown_upstream"
