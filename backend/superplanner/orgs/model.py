"""Organisations contract (M5-DESIGN 3.4; frozen at S0)."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints


class _In(BaseModel):
    model_config = ConfigDict(extra="forbid")


Slug = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")]
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]
PlantCode = Annotated[str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,31}$")]
PLANT_ROLES = ("plant_admin", "planner", "purchaser", "store_keeper", "approver", "viewer", "operator", "supervisor",
               "qa_inspector", "qa_engineer", "qa_approver", "metrology",   # M7-DESIGN 9.1
               "plant_manager", "auditor",                                  # M8-DESIGN 11
               "executive")                                                 # M9-DESIGN 9


class OrgIn(_In):
    name: Name
    slug: Slug
    require_2fa: bool = False


class OrgUpdate(_In):
    name: Name
    require_2fa: bool = False
    #: M7-DESIGN 4.6: idle timeout of the organisation's people (None = platform default; Part 11: 15)
    session_idle_minutes: Annotated[int, Field(ge=5, le=1440)] | None = None


class OrgRecord(BaseModel):
    id: str
    name: str
    slug: str
    require_2fa: bool
    session_idle_minutes: int | None = None
    my_role: Literal["org_admin", "org_member"] | None = None
    plants: int = 0
    members: int = 0
    row_version: int
    created_at: datetime


class OrgMemberIn(_In):
    email: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=254)]
    org_role: Literal["org_admin", "org_member"] = "org_member"


class OrgMemberUpdate(_In):
    org_role: Literal["org_admin", "org_member"] | None = None
    #: 15.WP-S: org admins disable / enable the member's account (sessions and API tokens stop working)
    disabled: bool | None = None


class OrgMemberRecord(BaseModel):
    id: str
    user: dict[str, Any]                 # {id, email, display_name, disabled}
    org_role: str
    plants: list[dict[str, Any]] = Field(default_factory=list)   # [{plant_owner_id, code, roles}]
    row_version: int
    created_at: datetime
    esig: dict[str, Any] | None = None   # M7: {enrolled, revoked, legal_name, locked_until}


class OrgPlantIn(_In):
    code: PlantCode
    name: Name
    utc_offset: Annotated[str, StringConstraints(pattern=r"^[+-](0\d|1[0-4]):[0-5]\d$")] = "+00:00"
    time_zone: Annotated[str, StringConstraints(max_length=64)] | None = None
    #: M9-DESIGN 2 / 4: a plant or a distribution centre; country (plant attribute) and currency
    kind: Literal["plant", "dc"] = "plant"
    country: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z]{2}$")] | None = None
    currency: Annotated[str, StringConstraints(strip_whitespace=True, to_upper=True, pattern=r"^[A-Z]{3}$")] | None = None


class OrgPlantUpdate(_In):
    name: Name
    kind: Literal["plant", "dc"] | None = None          # M9 4: to `dc` only without lines (409 NET_DC_HAS_LINES)


class NetworkIn(_In):
    """O1 (M9-DESIGN 4): the organisation's network workspace."""
    name: Name = "Network"
    time_zone: Annotated[str, StringConstraints(max_length=64)] | None = None


class OrgPlantRecord(BaseModel):
    id: str
    code: str
    name: str
    plant_owner_id: str
    kind: Literal["plant", "dc", "network"] = "plant"
    my_roles: list[str] = Field(default_factory=list)
    row_version: int
    created_at: datetime


class PlantRolesIn(_In):
    user_id: Annotated[str, StringConstraints(max_length=64)]
    roles: Annotated[list[Literal["plant_admin", "planner", "purchaser", "store_keeper", "approver", "viewer",
                                  "operator", "supervisor", "qa_inspector", "qa_engineer", "qa_approver",
                                  "metrology", "plant_manager", "auditor", "executive"]], Field(max_length=15)]   # [] removes the membership


class PublishIn(_In):
    source_plant: Annotated[str, StringConstraints(max_length=64)]       # plant owner id
    target_plants: Annotated[list[Annotated[str, StringConstraints(max_length=64)]], Field(min_length=1,
                                                                                            max_length=50)]
    scope: Literal["items", "master"] = "items"
    part_number_prefix: Annotated[str, StringConstraints(max_length=64)] | None = None


class PublishRecord(BaseModel):
    id: str
    org_id: str
    source_owner_id: str
    target_owner_ids: list[str]
    scope: str
    part_number_prefix: str | None = None
    status: Literal["queued", "running", "completed", "failed"]
    results: dict[str, Any] | None = None
    created_at: datetime
    finished_at: datetime | None = None


class OrgOverview(BaseModel):
    org: dict[str, Any]
    plants: list[dict[str, Any]]         # [{plant: {...}, visible, kpis: {otd, oee, ...}, late_demand, open_triggers,
    #                                      integration: {enabled, dead_deliveries, last_batch_at}}]
