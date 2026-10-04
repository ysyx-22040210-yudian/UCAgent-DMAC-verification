"""Typed HTTP Campaign operations sharing authentication, CSRF and platform storage."""

from fastapi import Depends, HTTPException
from pydantic import Field

from ucagent.platform.campaign import CampaignCreate, CampaignModel, Digest, ProposalCreate
from .campaign_service import CampaignConflict
from ucagent.eda.npi import NpiQuery


class CampaignAction(CampaignModel):
    """Require an observed revision for any coordinator state transition."""

    revision: int = Field(ge=0)


class ProposalDecision(CampaignModel):
    """Bind human candidate review to the baseline shown in the diff."""

    fingerprint: Digest
    note: str = Field(min_length=1, max_length=4000)


def register_campaign_routes(router, runtime, check_csrf):
    """Mount the Campaign contract on the existing authenticated versioned router."""
    service = runtime.campaigns
    from .npi_service import NpiService
    runtime.npi = NpiService(runtime)

    def invoke(operation, *args):
        """Map bounded domain errors without exposing raw internal exceptions."""
        try:
            return operation(*args)
        except CampaignConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except (ValueError, FileNotFoundError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.get("/capabilities")
    def capabilities():
        """Show feature-specific configuration and real-acceptance requirements."""
        return service.capabilities()

    @router.post("/npi/queries", dependencies=[Depends(check_csrf)])
    def create_npi_query(body: NpiQuery):
        """Query a signed artifact with literal selectors and administrator-owned tooling."""
        return invoke(runtime.npi.create, body)

    @router.get("/npi/queries/{query_id}")
    def get_npi_query(query_id: str):
        """Return bounded, signed read-only NPI query evidence."""
        return invoke(runtime.npi.get, query_id)

    @router.get("/campaigns")
    def campaigns():
        """List persistent design-verification tasks."""
        return service.list()

    @router.post("/campaigns", dependencies=[Depends(check_csrf)])
    def create_campaign(body: CampaignCreate):
        """Freeze approved inputs and budgets without launching unapproved work."""
        return invoke(service.create, body)

    @router.get("/campaigns/{campaign_id}")
    def campaign(campaign_id: str):
        """Read the full stage DAG, blockers and pending candidate reviews."""
        return invoke(service.get, campaign_id)

    @router.post("/campaigns/{campaign_id}/pause", dependencies=[Depends(check_csrf)])
    def pause(campaign_id: str, body: CampaignAction):
        """Pause scheduling and cancel any currently linked execution."""
        return invoke(service.transition, campaign_id, "pause", body.revision)

    @router.post("/campaigns/{campaign_id}/resume", dependencies=[Depends(check_csrf)])
    def resume(campaign_id: str, body: CampaignAction):
        """Recheck the complete baseline before resuming approved coordination."""
        return invoke(service.transition, campaign_id, "resume", body.revision)

    @router.post("/campaigns/{campaign_id}/cancel", dependencies=[Depends(check_csrf)])
    def cancel(campaign_id: str, body: CampaignAction):
        """Cancel coordination without removing evidence or marking verification passed."""
        return invoke(service.transition, campaign_id, "cancel", body.revision)

    @router.post("/proposals", dependencies=[Depends(check_csrf)])
    def propose(body: ProposalCreate):
        """Create an isolated exact-input candidate and a reviewable diff."""
        return invoke(service.propose, body)

    @router.get("/proposals")
    def proposals(campaign_id: str):
        """Read proposals for one campaign, including rejected candidates."""
        invoke(service.get, campaign_id)
        items = service.proposals(campaign_id)
        return {"items": items, "count": len(items)}

    @router.post("/proposals/{proposal_id}/approve", dependencies=[Depends(check_csrf)])
    def approve(proposal_id: str, body: ProposalDecision):
        """Approve the unchanged candidate for testing, not for mainline integration."""
        return invoke(service.review_proposal, proposal_id, "approve", body.fingerprint, body.note)

    @router.post("/proposals/{proposal_id}/reject", dependencies=[Depends(check_csrf)])
    def reject(proposal_id: str, body: ProposalDecision):
        """Reject a candidate while retaining its review evidence."""
        return invoke(service.review_proposal, proposal_id, "reject", body.fingerprint, body.note)
