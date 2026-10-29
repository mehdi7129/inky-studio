"""Attested, bounded system-setup IPC; no local readiness or UID substitute.

The closed rules below are mechanically transcribed from ipc-contract.json
SHA256 9ee767fbdb75250546ca950c4d1fff58c8e1d0b6b9029742b61efea9bd2a7b52.
The OS proof owns peer identity; hashes only bind the received records.
"""
from __future__ import annotations

import asyncio
import hashlib
import ipaddress
import json
import re
from pathlib import Path
from uuid import uuid4

from .connected_peer import connected_peer_scope

_REQUEST_LIMIT = 8192
_RESPONSE_LIMIT = 16384
_OPERATION_TIMEOUT_SECONDS = {
    "setup.apply": 55,
    # AP start includes bounded country/preflight/activation work plus graph
    # verification. Read/stop retain smaller, explicit operation budgets.
    "setup.ap.start": 180,
    "setup.ap.stop": 60,
    "setup.ap.status": 60,
}

_DEFINITIONS = {
    'Workflow': ('object', {'initialization_intent': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'initialization_receipt_digest': ('string', '^[0-9a-f]{64}$', None), 'frame_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'spki_sha256': ('string', '^[0-9a-f]{64}$', None)}),
    'OwnerBinding': ('object', {'initialization_intent': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'initialization_receipt_digest': ('string', '^[0-9a-f]{64}$', None), 'frame_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'spki_sha256': ('string', '^[0-9a-f]{64}$', None), 'credential_epoch': ('string', '^[0-9a-f]{64}$', None), 'owner_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'claim_request_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'session_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None)}),
    'ObservedBinding': ('object', {'initialization_intent': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'initialization_receipt_digest': ('string', '^[0-9a-f]{64}$', None), 'frame_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'spki_sha256': ('string', '^[0-9a-f]{64}$', None), 'credential_epoch': ('string', '^[0-9a-f]{64}$', None), 'owner_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'claim_request_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'session_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'boot_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'candidate_sha256': ('string', '^[0-9a-f]{64}$', None), 'context_sha256': ('string', '^[0-9a-f]{64}$', None), 'main_invocation_id': ('string', '^[0-9a-f]{32}$', None)}),
    'Gate': ('object', {'boot_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'candidate_sha256': ('string', '^[0-9a-f]{64}$', None), 'record_sha256': ('string', '^[0-9a-f]{64}$', None), 'closed_boottime_ns': ('integer', 0, 9223372036854775807, None), 'nm_wireless_enabled': ('const', False), 'wlan_soft_blocked': ('const', True), 'restore_policy': ('const', 'systemd-rfkill-masked')}),
    'Challenge': ('object', {'operation_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'supersedes_operation_id': ('one', (('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), ('const', None))), 'challenge_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'nonce': ('string', '^[0-9a-f]{64}$', None), 'issued_boottime_ns': ('integer', 0, 9223372036854775807, None), 'expires_boottime_ns': ('integer', 0, 9223372036854775807, None), 'binding': ('ref', 'ObservedBinding')}),
    'Clock': ('object', {'utc_seconds': ('integer', 1767225600, None, 4102444800), 'effect_start_boottime_ns': ('integer', 0, 9223372036854775807, None), 'effect_end_boottime_ns': ('integer', 0, 9223372036854775807, None), 'read_start_boottime_ns': ('integer', 0, 9223372036854775807, None), 'read_end_boottime_ns': ('integer', 0, 9223372036854775807, None), 'realtime_ns': ('integer', 0, 9223372036854775807, None), 'error_lower_ns': ('integer', -2000000000, 2000000000, None), 'error_upper_ns': ('integer', -2000000000, 2000000000, None), 'time_policy_sha256': ('string', '^[0-9a-f]{64}$', None)}),
    'Country': ('object', {'requested_country': ('string', '^[A-Z]{2}$', None), 'firmware_country': ('string', '^[A-Z]{2}$', None), 'firmware_ccode': ('string', '^[A-Z]{2}$', None), 'firmware_revision': ('integer', -2147483648, 2147483647, None), 'global_country': ('string', '^[A-Z]{2}$', None), 'phy_label': ('string', '^[A-Z0-9]{2}$', None), 'wiphy_index': ('integer', 0, 255, None), 'interface': ('const', 'wlan0'), 'channel_evidence_sha256': ('string', '^[0-9a-f]{64}$', None), 'observed_boottime_ns': ('integer', 0, 9223372036854775807, None)}),
    'Radio': ('object', {'wireless_enabled': ('const', True), 'wlan_soft_blocked': ('const', False), 'wlan_hard_blocked': ('const', False), 'wiphy_index': ('integer', 0, 255, None), 'interface': ('const', 'wlan0'), 'nm_unique_owner': ('string', '^:[0-9]+\\.[0-9]+$', None), 'observed_boottime_ns': ('integer', 0, 9223372036854775807, None)}),
    'EffectReceipt': ('object', {'schema_version': ('const', 1), 'operation_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'request_sha256': ('string', '^[0-9a-f]{64}$', None), 'binding': ('ref', 'ObservedBinding'), 'gate': ('ref', 'Gate'), 'clock': ('ref', 'Clock'), 'country': ('ref', 'Country'), 'radio': ('ref', 'Radio'), 'record_sha256': ('string', '^[0-9a-f]{64}$', None)}),
    'Publication': ('object', {'publication_operation_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'initial_certificate_sha256': ('string', '^[0-9a-f]{64}$', None), 'frame_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'spki_sha256': ('string', '^[0-9a-f]{64}$', None), 'initial_setup_operation_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None)}),
    'NetworkObservation': ('object', {'id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'owner_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'state': ('const', 'committed'), 'profile_uuid': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'device': ('const', 'wlan0'), 'nm_unique_owner': ('string', '^:[0-9]+\\.[0-9]+$', None), 'boot_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'ipv4': ('array', 0, 16, True, ('string', None, 'ipv4')), 'active_profile_uuid': ('one', (('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), ('const', None))), 'profile_persistent': ('const', True), 'observation_sha256': ('string', '^[0-9a-f]{64}$', None), 'commit_boot_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'commit_nm_unique_owner': ('string', '^:[0-9]+\\.[0-9]+$', None)}),
    'Completion': ('object', {'completion_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'workflow': ('ref', 'Workflow'), 'owner_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'claim_request_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'credential_epoch': ('string', '^[0-9a-f]{64}$', None), 'operation_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'effect_receipt_sha256': ('string', '^[0-9a-f]{64}$', None), 'publication': ('ref', 'Publication'), 'country': ('string', '^[A-Z]{2}$', None), 'created_boot_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'record_sha256': ('string', '^[0-9a-f]{64}$', None), 'initial_profile_uuid': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'initial_network_transaction_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None)}),
    'Live': ('object', {'boot_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'candidate_sha256': ('string', '^[0-9a-f]{64}$', None), 'context_sha256': ('string', '^[0-9a-f]{64}$', None), 'readiness': ('enum', ('unavailable', 'wlan_closed', 'country_radio_ready', 'network_ready')), 'clock_status': ('enum', ('not_attested_current_boot', 'owner_asserted_current_boot')), 'country_receipt_sha256': ('one', (('string', '^[0-9a-f]{64}$', None), ('const', None))), 'radio_receipt_sha256': ('one', (('string', '^[0-9a-f]{64}$', None), ('const', None))), 'https_origin': ('one', (('string', '^https://inky-[0-9a-f]{32}\\.local:8443$', None), ('const', None))), 'origin_status': ('enum', ('unavailable', 'avahi_current')), 'network': ('one', (('ref', 'NetworkObservation'), ('const', None)))}),
    'Operation': ('object', {'operation_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'state': ('enum', ('pending', 'uncertain', 'effects_completed', 'superseded')), 'request_sha256': ('string', '^[0-9a-f]{64}$', None), 'binding': ('ref', 'ObservedBinding'), 'supersedes_operation_id': ('one', (('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), ('const', None))), 'receipt': ('one', (('ref', 'EffectReceipt'), ('const', None)))}),
    'Snapshot': ('object', {'workflow': ('ref', 'Workflow'), 'state': ('enum', ('not_started', 'challenged', 'pending', 'uncertain', 'effects_completed', 'completed')), 'latest_operation_id': ('one', (('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), ('const', None))), 'operation': ('one', (('ref', 'Operation'), ('const', None))), 'completion': ('one', (('ref', 'Completion'), ('const', None))), 'live': ('ref', 'Live'), 'network_head': ('one', (('ref', 'NetworkHead'), ('const', None)))}),
    'NetworkHead': ('object', {'completion_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'revision': ('integer', 1, 9223372036854775807, None), 'profile_uuid': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'network_transaction_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'owner_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'country': ('string', '^[A-Z]{2}$', None), 'updated_boot_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'record_sha256': ('string', '^[0-9a-f]{64}$', None), 'source_observation_sha256': ('string', '^[0-9a-f]{64}$', None)}),
}

_REQUESTS = {
    'setup.open': ('object', {'v': ('const', 1), 'id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'op': ('const', 'setup.open'), 'args': ('object', {'binding': ('ref', 'OwnerBinding')})}),
    'setup.inspect': ('object', {'v': ('const', 1), 'id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'op': ('const', 'setup.inspect'), 'args': ('object', {'workflow': ('ref', 'Workflow')})}),
    'setup.challenge': ('object', {'v': ('const', 1), 'id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'op': ('const', 'setup.challenge'), 'args': ('object', {'operation_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'supersedes_operation_id': ('one', (('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), ('const', None)))})}),
    'setup.apply': ('object', {'v': ('const', 1), 'id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'op': ('const', 'setup.apply'), 'args': ('object', {'operation_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'supersedes_operation_id': ('one', (('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), ('const', None))), 'challenge_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'nonce': ('string', '^[0-9a-f]{64}$', None), 'utc_seconds': ('integer', 1767225600, None, 4102444800), 'country': ('string', '^[A-Z]{2}$', None)})}),
    'setup.status': ('object', {'v': ('const', 1), 'id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'op': ('const', 'setup.status'), 'args': ('object', {'operation_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None)})}),
    'setup.complete': ('object', {'v': ('const', 1), 'id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'op': ('const', 'setup.complete'), 'args': ('object', {'operation_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'publication': ('ref', 'Publication'), 'network_transaction_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None)})}),
    'setup.resume': ('object', {'v': ('const', 1), 'id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'op': ('const', 'setup.resume'), 'args': ('object', {'completion_id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None)})}),
}

_RESPONSES = {
    'setup.open': ('object', {'v': ('const', 1), 'id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'ok': ('const', True), 'result': ('object', {'binding': ('ref', 'ObservedBinding')})}),
    'setup.inspect': ('object', {'v': ('const', 1), 'id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'ok': ('const', True), 'result': ('ref', 'Snapshot')}),
    'setup.challenge': ('object', {'v': ('const', 1), 'id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'ok': ('const', True), 'result': ('ref', 'Challenge')}),
    'setup.apply': ('object', {'v': ('const', 1), 'id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'ok': ('const', True), 'result': ('ref', 'Operation')}),
    'setup.status': ('object', {'v': ('const', 1), 'id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'ok': ('const', True), 'result': ('object', {'operation': ('ref', 'Operation'), 'completion': ('one', (('ref', 'Completion'), ('const', None))), 'live': ('ref', 'Live'), 'network_head': ('one', (('ref', 'NetworkHead'), ('const', None)))})}),
    'setup.complete': ('object', {'v': ('const', 1), 'id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'ok': ('const', True), 'result': ('ref', 'Completion')}),
    'setup.resume': ('object', {'v': ('const', 1), 'id': ('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), 'ok': ('const', True), 'result': ('object', {'completion': ('ref', 'Completion'), 'live': ('ref', 'Live'), 'network_head': ('one', (('ref', 'NetworkHead'), ('const', None)))})}),
}

_ERROR = ('object', {'v': ('const', 1), 'id': ('one', (('string', '^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', None), ('const', None))), 'ok': ('const', False), 'error': ('enum', ('invalid_request', 'forbidden', 'unavailable', 'not_found', 'conflict', 'challenge_expired', 'session_closed', 'ledger_full', 'effect_uncertain', 'country_unconfirmed', 'cleanup_unconfirmed', 'network_unconfirmed', 'publication_conflict', 'origin_unavailable'))})

# AP extension transcribed from OS canonical contract SHA256
# 101d169b3eb5a1ecbfd9345e874dbf686095b304efe1db678963ceac16e81a06.
# Existing setup record shapes remain unchanged.
# Root-owned AP credentials are transported only over this attested IPC and QR.
_DEFINITIONS["AccessPoint"] = ("object", {
    "state": ("enum", ("active", "stopped", "expired")),
    "boot_id": _DEFINITIONS["ObservedBinding"][1]["boot_id"],
    "ap_id": _DEFINITIONS["ObservedBinding"][1]["session_id"],
    "country": ("const", "FR"), "interface": ("const", "wlan0"),
    "ssid": ("string", r"^Inky-[0-9a-f]{8}$", None),
    "passphrase": ("string", r"^[0-9a-f]{24}$", None),
    "host": ("const", "192.168.4.1"), "port": ("const", 9443),
    "expires_boottime_ns": ("integer", 0, 9223372036854775807, None),
})
for _ap_operation in ("setup.ap.start", "setup.ap.stop", "setup.ap.status"):
    _REQUESTS[_ap_operation] = ("object", {
        "v": ("const", 1), "id": _DEFINITIONS["ObservedBinding"][1]["session_id"],
        "op": ("const", _ap_operation), "args": ("object", {"workflow": ("ref", "Workflow")}),
    })
    _RESPONSES[_ap_operation] = ("object", {
        "v": ("const", 1), "id": _DEFINITIONS["ObservedBinding"][1]["session_id"],
        "ok": ("const", True), "result": ("ref", "AccessPoint"),
    })
_ERROR[1]["error"] = ("enum", (*_ERROR[1]["error"][1], "expired", "reconciliation_required",
    "policy_invalid", "invalid_clock", "random_unavailable", "closed", "ap_unavailable",
    "ap_ownership_changed", "ap_timeout", "ap_effect_uncertain", "source_changed",
    "writer_guard_failed", "radio_unconfirmed", "ap_profile_changed", "ap_inventory_changed",
    "nm_owner_changed", "timeout"))

class SetupUnavailable(Exception):
    """Fixed diagnostics only; never expose root-service or proof exceptions."""

    def __init__(self, code="unavailable"):
        self.code = code
        super().__init__(code)


def canonical_hash(value, *, exclude=None):
    data = {key: item for key, item in value.items() if key != exclude}
    return hashlib.sha256((json.dumps(data, sort_keys=True, ensure_ascii=True,
                                    separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")).hexdigest()


def _check(condition):
    if not condition:
        raise SetupUnavailable("response_invalid")


def _validate(value, rule):
    kind, *args = rule
    if kind == "ref":
        return _validate(value, _DEFINITIONS[args[0]])
    if kind == "const":
        _check(type(value) is type(args[0]) and value == args[0])
    elif kind == "enum":
        _check(type(value) is str and value in args[0])
    elif kind == "one":
        for choice in args[0]:
            try:
                _validate(value, choice)
                return
            except SetupUnavailable:
                pass
        raise SetupUnavailable("response_invalid")
    elif kind == "object":
        _check(type(value) is dict and set(value) == set(args[0]))
        for key, child in args[0].items():
            _validate(value[key], child)
    elif kind == "integer":
        low, high, exclusive = args
        _check(type(value) is int and (low is None or value >= low)
               and (high is None or value <= high) and (exclusive is None or value < exclusive))
    elif kind == "string":
        pattern, fmt = args
        _check(type(value) is str and (pattern is None or re.fullmatch(pattern, value) is not None))
        if fmt == "ipv4":
            try:
                _check(str(ipaddress.IPv4Address(value)) == value)
            except ValueError:
                raise SetupUnavailable("response_invalid") from None
    elif kind == "array":
        low, high, unique, child = args
        _check(type(value) is list and len(value) >= low and (high is None or len(value) <= high))
        if unique:
            _check(len({json.dumps(item, sort_keys=True) for item in value}) == len(value))
        for item in value:
            _validate(item, child)
    else:
        raise SetupUnavailable("response_invalid")


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        _check(key not in result)
        result[key] = value
    return result


def _integer(raw):
    _check(re.fullmatch(r"0|-?[1-9][0-9]*", raw) is not None and len(raw) <= 20)
    return int(raw)


def _reject(_):
    raise SetupUnavailable("response_invalid")


def _decode(raw):
    _check(type(raw) is bytes and len(raw) <= _RESPONSE_LIMIT and raw.endswith(b"\n")
           and raw.count(b"\n") == 1)
    try:
        value = json.loads(raw.decode("utf-8", errors="strict"), object_pairs_hook=_pairs,
                           parse_int=_integer, parse_float=_reject, parse_constant=_reject)
        def depth(item, level=0):
            _check(level <= 24)
            if isinstance(item, dict):
                for child in item.values():
                    depth(child, level + 1)
            elif isinstance(item, list):
                for child in item:
                    depth(child, level + 1)
        depth(value)
        return value
    except (ValueError, UnicodeError, RecursionError):
        raise SetupUnavailable("response_invalid") from None


async def _read_line(reader):
    raw = bytearray()
    while True:
        chunk = await reader.read(min(4096, _RESPONSE_LIMIT + 1 - len(raw)))
        if not chunk:
            raise SetupUnavailable("response_invalid")
        raw.extend(chunk)
        _check(len(raw) <= _RESPONSE_LIMIT)
        if b"\n" in raw:
            _check(raw.count(b"\n") == 1 and raw.endswith(b"\n"))
            return bytes(raw)


def _workflow(binding):
    return {key: binding[key] for key in _DEFINITIONS["Workflow"][1]}


def _integrity(value):
    """Hashes and cross-record identities, independently of transport authority."""
    if type(value) is dict:
        for field in ("record_sha256", "observation_sha256"):
            if field in value:
                _check(canonical_hash(value, exclude=field) == value[field])
        for child in value.values():
            _integrity(child)
    elif type(value) is list:
        for child in value:
            _integrity(child)


def _operation(operation):
    receipt = operation["receipt"]
    _check((operation["state"] not in {"pending", "uncertain"} or receipt is None)
           and (operation["state"] != "effects_completed" or receipt is not None))
    if receipt is None:
        return
    for field in ("operation_id", "request_sha256", "binding"):
        _check(receipt[field] == operation[field])
    binding, gate, clock, country, radio = (receipt[key] for key in ("binding", "gate", "clock", "country", "radio"))
    _check(gate["boot_id"] == binding["boot_id"] and gate["candidate_sha256"] == binding["candidate_sha256"])
    _check(gate["closed_boottime_ns"] <= clock["effect_start_boottime_ns"]
           <= clock["effect_end_boottime_ns"] <= clock["read_start_boottime_ns"]
           <= clock["read_end_boottime_ns"] <= country["observed_boottime_ns"]
           <= radio["observed_boottime_ns"])
    requested = clock["utc_seconds"] * 1_000_000_000
    _check(clock["error_lower_ns"] == clock["realtime_ns"] - requested
           - (clock["read_end_boottime_ns"] - clock["effect_start_boottime_ns"])
           and clock["error_upper_ns"] == clock["realtime_ns"] - requested
           - (clock["read_start_boottime_ns"] - clock["effect_end_boottime_ns"])
           and clock["read_end_boottime_ns"] - clock["read_start_boottime_ns"] < 2_000_000_000)
    _check(country["requested_country"] == country["firmware_country"]
           == country["firmware_ccode"] == country["global_country"])
    _check(country["wiphy_index"] == radio["wiphy_index"])


def _semantics(operation, arguments, result, *, binding=None, boot_id=None):
    _integrity(result)
    if operation in {"setup.ap.start", "setup.ap.stop", "setup.ap.status"}:
        _check(result["boot_id"] == boot_id)
        _check(operation != "setup.ap.start" or result["state"] == "active")
        _check(operation != "setup.ap.stop" or result["state"] in {"stopped", "expired"})
        if binding is not None:
            _check(_workflow(binding) == arguments["workflow"])
        return
    if operation == "setup.open":
        _check({key: result["binding"][key] for key in arguments["binding"]} == arguments["binding"])
        _check(result["binding"]["boot_id"] == boot_id)
        return
    if operation == "setup.challenge":
        _check(result["binding"] == binding and result["operation_id"] == arguments["operation_id"]
               and result["supersedes_operation_id"] == arguments["supersedes_operation_id"]
               and result["expires_boottime_ns"] - result["issued_boottime_ns"] == 30_000_000_000)
        return
    if operation == "setup.apply":
        _operation(result)
        _check({key: result["binding"][key] for key in binding if key not in
                {"session_id", "boot_id", "candidate_sha256", "context_sha256", "main_invocation_id"}}
               == {key: binding[key] for key in binding if key not in
                   {"session_id", "boot_id", "candidate_sha256", "context_sha256", "main_invocation_id"}}
               and result["operation_id"] == arguments["operation_id"]
               and result["supersedes_operation_id"] == arguments["supersedes_operation_id"])
        material = {"workflow": _workflow(binding), **{key: binding[key] for key in
                    ("owner_id", "claim_request_id", "credential_epoch")}, **arguments}
        _check(result["request_sha256"] == canonical_hash(material))
        if result["receipt"] is not None:
            receipt = result["receipt"]
            _check(receipt["clock"]["utc_seconds"] == arguments["utc_seconds"]
                   and receipt["country"]["requested_country"] == arguments["country"])
        return
    if operation == "setup.complete":
        completion, live, network_head = result, None, None
        _check(completion["operation_id"] == arguments["operation_id"]
               and completion["publication"] == arguments["publication"]
               and completion["initial_network_transaction_id"] == arguments["network_transaction_id"])
        _check(completion["workflow"] == _workflow(binding))
        for key in ("owner_id", "claim_request_id", "credential_epoch"):
            _check(completion[key] == binding[key])
    else:
        completion, live, network_head = (result[key] for key in ("completion", "live", "network_head"))
        current = result.get("operation")
        if current is not None:
            _operation(current)
        if operation == "setup.inspect":
            _check(result["workflow"] == arguments["workflow"])
            if current is not None:
                _check(_workflow(current["binding"]) == arguments["workflow"]
                       and current["operation_id"] == result["latest_operation_id"])
            if completion is not None:
                _check(completion["workflow"] == arguments["workflow"])
            if result["state"] == "completed":
                _check(completion is not None and current is not None
                       and completion["operation_id"] == current["operation_id"])
            elif completion is not None:
                # Passive completion history preserves NORMAL while a fresh,
                # explicitly admitted recovery operation is still unfinished.
                _check(current is not None and current["operation_id"] != completion["operation_id"]
                       and result["state"] in {"pending", "uncertain", "effects_completed"})
        elif operation == "setup.status":
            _check(current["operation_id"] == arguments["operation_id"])
            if completion is not None:
                _check(completion["workflow"] == _workflow(current["binding"]))
        elif operation == "setup.resume":
            _check(completion["completion_id"] == arguments["completion_id"])
    if completion is not None:
        for field in ("frame_id", "spki_sha256"):
            _check(completion["publication"][field] == completion["workflow"][field])
    if live is not None:
        _check(live["boot_id"] == boot_id)
        _check((live["https_origin"] is not None) == (live["origin_status"] == "avahi_current"))
        network = live["network"]
        if network is not None:
            _check(network["boot_id"] == live["boot_id"])
        if live["readiness"] == "network_ready":
            _check(network is not None and network["ipv4"]
                   and network["active_profile_uuid"] == network["profile_uuid"])
    if network_head is not None:
        _check(completion is not None and network_head["completion_id"] == completion["completion_id"]
               and network_head["country"] == completion["country"])
        if operation == "setup.resume" and live["network"] is not None:
            network = live["network"]
            _check(network_head["source_observation_sha256"] == network["observation_sha256"]
                   and network_head["profile_uuid"] == network["profile_uuid"]
                   and network_head["network_transaction_id"] == network["id"]
                   and network_head["owner_id"] == network["owner_id"])


def _boot_id():
    value = Path("/proc/sys/kernel/random/boot_id").read_text(encoding="ascii").strip()
    _validate(value, _DEFINITIONS["ObservedBinding"][1]["boot_id"])
    return value


class SetupChannel:
    """One owner TLS peer, one admitted connection and one outstanding RPC.

    close() sends EOF immediately. The owning runtime must then await drain()
    before releasing its main writer lease. Caller cancellation never abandons
    an admitted RPC or the connected-peer proof.
    """

    def __init__(self, client, reader, writer, proof):
        self.client, self.reader, self.writer, self.proof = client, reader, writer, proof
        self.binding = None
        self.closed = False
        self._pending = set()
        self._busy = False
        self._released = False

    def close(self):
        self.closed = True
        self.writer.close()

    async def drain(self):
        self.close()
        cancelled = False
        while self._pending:
            try:
                await asyncio.shield(asyncio.gather(*tuple(self._pending), return_exceptions=True))
            except asyncio.CancelledError:
                cancelled = True
        closing = asyncio.create_task(self.writer.wait_closed())
        while not closing.done():
            try:
                await asyncio.shield(closing)
            except asyncio.CancelledError:
                cancelled = True
            except Exception:
                break
        try:
            closing.result()
        except Exception:
            pass
        if not self._released:
            self._released = True
            try:
                self.proof.__exit__(None, None, None)
            except Exception:
                raise SetupUnavailable("unavailable") from None
        if cancelled:
            raise asyncio.CancelledError

    async def call(self, operation, **arguments):
        if self.closed:
            raise SetupUnavailable("session_closed")
        if self._busy:
            raise SetupUnavailable("unavailable")
        self._busy = True
        task = asyncio.create_task(self._call(operation, arguments))
        self._pending.add(task)
        def done(completed):
            self._pending.discard(completed)
            self._busy = False
            if not completed.cancelled():
                completed.exception()
        task.add_done_callback(done)
        return await asyncio.shield(task)

    async def _call(self, operation, arguments):
        try:
            if type(operation) is not str or operation not in _REQUESTS:
                raise SetupUnavailable("invalid_request")
            if operation in {"setup.challenge", "setup.apply", "setup.complete"} and self.binding is None:
                raise SetupUnavailable("session_closed")
            request = {"v": 1, "id": str(uuid4()), "op": operation, "args": arguments}
            try:
                _validate(request, _REQUESTS[operation])
            except SetupUnavailable:
                raise SetupUnavailable("invalid_request") from None
            raw = (json.dumps(request, ensure_ascii=True, separators=(",", ":"), allow_nan=False) + "\n").encode("ascii")
            if len(raw) > _REQUEST_LIMIT:
                raise SetupUnavailable("invalid_request")
            async with asyncio.timeout(_OPERATION_TIMEOUT_SECONDS.get(operation, 15)):
                self.writer.write(raw)
                await self.writer.drain()
                response = _decode(await _read_line(self.reader))
            if response.get("ok") is False:
                _validate(response, _ERROR)
                _check(response["id"] == request["id"])
                raise SetupUnavailable(response["error"])
            _validate(response, _RESPONSES[operation])
            _check(response["id"] == request["id"])
            result = response["result"]
            _semantics(operation, arguments, result, binding=self.binding, boot_id=self.client.boot_id())
            return result
        except SetupUnavailable as error:
            if error.code == "response_invalid":
                self.close()
            raise
        except Exception:
            self.close()
            raise SetupUnavailable("unavailable") from None


class SystemSetupClient:
    def __init__(self, path=None, *, peer_guard=None, boot_id=None):
        self.path = path or "/run/inkyos-system-setup/control.sock"
        self.peer_guard = peer_guard
        self.boot_id = boot_id or _boot_id

    async def _connect(self):
        if self.peer_guard is None:
            raise SetupUnavailable("unavailable")
        writer = None
        try:
            async with asyncio.timeout(15):
                reader, writer = await asyncio.open_unix_connection(self.path, limit=_RESPONSE_LIMIT)
            connection = writer.get_extra_info("socket")
            if connection is None:
                raise SetupUnavailable("unavailable")
            proof = connected_peer_scope(connection, self.peer_guard)
            proof.__enter__()
            return SetupChannel(self, reader, writer, proof)
        except BaseException as error:
            if writer is not None:
                writer.close()
                closing = asyncio.create_task(writer.wait_closed())
                while not closing.done():
                    try:
                        await asyncio.shield(closing)
                    except asyncio.CancelledError:
                        pass
                    except Exception:
                        break
                try:
                    closing.result()
                except Exception:
                    pass
            if isinstance(error, asyncio.CancelledError):
                raise
            raise SetupUnavailable("unavailable") from None

    async def open(self, binding):
        channel = await self._connect()
        try:
            result = await channel.call("setup.open", binding=binding)
            channel.binding = result["binding"]
            return channel
        except BaseException:
            await channel.drain()
            raise

    async def _readonly(self, operation, **arguments):
        channel = await self._connect()
        try:
            return await channel.call(operation, **arguments)
        finally:
            await channel.drain()

    async def inspect(self, workflow):
        return await self._readonly("setup.inspect", workflow=workflow)

    async def status(self, operation_id):
        return await self._readonly("setup.status", operation_id=operation_id)

    async def resume(self, completion_id):
        return await self._readonly("setup.resume", completion_id=completion_id)

    async def ap_start(self, workflow):
        return await self._readonly("setup.ap.start", workflow=workflow)

    async def ap_stop(self, workflow):
        return await self._readonly("setup.ap.stop", workflow=workflow)

    async def ap_status(self, workflow):
        return await self._readonly("setup.ap.status", workflow=workflow)
