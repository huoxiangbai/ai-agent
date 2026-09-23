"""Execution ledger constants.

Ported from ``org.wwz.ai.domain.agent.ledger.model.ExecutionLedgerConstants``.
"""

from __future__ import annotations

STATUS_RUNNING = 0
STATUS_SUCCESS = 1
STATUS_FAILED = 2
STATUS_TIMEOUT = 3
STATUS_STOPPED = 4
STATUS_WAITING_INPUT = 5

CALL_KIND_ASK = "ask"
CALL_KIND_ASK_TOOL = "askTool"
CALL_KIND_INTERNAL_DIGITAL_EMPLOYEE = "internalDigitalEmployee"
CALL_KIND_INTERNAL_COMPACT = "internalCompact"

ENTRY_AGENT_REACT = "react"
ENTRY_AGENT_PLAN_SOLVE = "plan_solve"

ARTIFACT_ROLE_INPUT = "input"
ARTIFACT_ROLE_OUTPUT = "output"

VISIBILITY_VISIBLE = "visible"
VISIBILITY_INTERNAL = "internal"

ARTIFACT_DELIMITER = "$$$"
ARTIFACT_KEY_SEPARATOR_REGEX = r"[、,，\r\n]+"
