"""LIVE integration tests: real Meta Model API inference. Excluded by default.

    pytest -m live            # needs MODEL_API_KEY; PROOFCAM_LIVE_IMAGES=first.jpg;second.jpg for real photos

These assert only safety properties that must hold for ANY real model output — never a specific verdict
(that would hardcode outcomes). Model quality is measured by the evaluation harness (Milestone 4).
"""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from proofcam.agent import InspectionAgent
from proofcam.config import MissingCredentialsError, Settings
from proofcam.images import load_image
from proofcam.meta_client import MetaClient
from proofcam.spec import InspectionSpec
from proofcam.trace import Trace

pytestmark = pytest.mark.live
SPEC = Path(__file__).resolve().parents[2] / "data" / "specs" / "router_switch.json"


@pytest.fixture
def live_settings() -> Settings:
    try:
        return Settings.from_env()
    except MissingCredentialsError:
        pytest.skip("MODEL_API_KEY not set")


def test_live_inspection_safety_properties(live_settings):
    paths = [p for p in os.environ.get("PROOFCAM_LIVE_IMAGES", "").split(";") if p]
    if not paths:
        pytest.skip("set PROOFCAM_LIVE_IMAGES to real photo paths")
    spec = InspectionSpec.load(SPEC)
    client = MetaClient(live_settings, Trace())
    agent = InspectionAgent(spec, client, live_settings)

    async def go():
        steps = []
        for p in paths:
            if agent.done:
                break
            steps.append(await agent.observe(load_image(p)))
        await client.aclose()
        return steps

    steps = asyncio.run(go())
    calls = agent.trace.model_calls()
    assert calls and all(c.source == "live" for c in calls)
    for st in steps:
        for a in st.assessments:
            if a.status == "VERIFIED":
                # A positive verdict must cite real support from every endpoint.
                assert all(ep.support for ep in a.endpoints)
                assert a.identity_state in ("established", "assumed_by_spec")
        if st.next_view:
            assert len(st.next_view.instruction) >= 15
